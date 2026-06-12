"""인시던트 상관 잡(F33, UC24).

5분 주기로 아직 인시던트에 묶이지 않은 최근 이상들을 서버 그룹으로 모아 하나의
인시던트로 묶는다. 개별 이상 알림 대신 인시던트 단위로 한 번만 알려 노이즈를 줄인다.

흐름:
1. 미할당 이상(incident_id IS NULL) 중 최근 10분 이내 것을 모은다.
2. 서버의 group_name 으로 묶는다. group_name 이 없으면 서버 단위(server:{id})로 본다.
3. 그룹마다 서버를 공유하는 OPEN 인시던트가 있으면 거기 부착, 없으면 새로 만든다.
4. 새 인시던트를 만들 때만 ADM 사용자 각각에게 INCIDENT 알림 1건씩 보낸다.
5. 묶인 이상의 최신 시각이 15분보다 오래된 OPEN 인시던트는 RESOLVED 로 자동 종료한다.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import AnomalyRecord, Incident, Notification, Server, User
from app.models.enums import IncidentStatus, UserRole
from app.services.incident import compute_severity
from app.services.scheduler_log import add_scheduler_log

logger = logging.getLogger(__name__)

# 미할당 이상을 모으는 시간 윈도우와, 새 이상이 없을 때 인시던트를 닫는 유휴 한계.
_CORRELATION_WINDOW = timedelta(minutes=10)
_AUTO_RESOLVE_IDLE = timedelta(minutes=15)


async def correlate_anomalies(*, session_factory: async_sessionmaker = SessionLocal) -> None:
    """미할당 이상을 그룹별로 인시던트에 묶고, 오래된 인시던트를 종료한다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            groups = await _group_unassigned_anomalies(db, now)
            for server_ids, anomalies in groups.values():
                await _correlate_group(db, server_ids, anomalies)
            await _auto_resolve_stale(db, now)
            # 대시보드(F21)용 실행 이력: 이번에 인시던트로 묶은 그룹 수를 처리량으로 남긴다.
            add_scheduler_log(db, "UC24", len(groups))
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("인시던트 상관 잡 실패")


async def _group_unassigned_anomalies(
    db: AsyncSession, now: datetime
) -> dict[str, tuple[set[int], list[AnomalyRecord]]]:
    """최근 윈도우 안의 미할당 이상을 그룹키별로 모은다.

    그룹키는 서버의 group_name, 없으면 server:{id}. 값은 (서버 id 집합, 이상 목록).
    """
    rows = (
        await db.execute(
            select(AnomalyRecord, Server.group_name)
            .join(Server, AnomalyRecord.server_id == Server.id)
            .where(
                AnomalyRecord.incident_id.is_(None),
                AnomalyRecord.detected_at >= now - _CORRELATION_WINDOW,
            )
        )
    ).all()

    groups: dict[str, tuple[set[int], list[AnomalyRecord]]] = defaultdict(
        lambda: (set(), [])
    )
    for anomaly, group_name in rows:
        key = group_name if group_name else f"server:{anomaly.server_id}"
        server_ids, anomalies = groups[key]
        server_ids.add(anomaly.server_id)
        anomalies.append(anomaly)
    return groups


async def _correlate_group(
    db: AsyncSession, server_ids: set[int], anomalies: list[AnomalyRecord]
) -> None:
    """그룹을 기존 OPEN 인시던트에 부착하거나 새 인시던트로 만든다."""
    # 읽고-나서-생성 사이에 DB 수준의 유일성 보장이 없어, 잡이 동시에 두 번 돌면
    # 인시던트가 중복 생성될 수 있다. 잡은 스케줄러 컨테이너가 단독 소유한다
    # (scheduling.py 참고)고 전제하므로 단일 인스턴스 가정이 유효하다.
    incident = await _find_open_incident_sharing_server(db, server_ids)
    is_new = incident is None
    if is_new:
        incident = Incident(status=IncidentStatus.OPEN.value, anomaly_count=0, server_ids=[])
        db.add(incident)
        await db.flush()  # incident.id 확보(이상 부착·알림 payload 에 필요)

    for anomaly in anomalies:
        anomaly.incident_id = incident.id
    incident.anomaly_count += len(anomalies)
    incident.server_ids = _merge_server_ids(incident.server_ids, server_ids)
    incident.severity = await _recompute_severity(db, incident.id)

    if is_new:
        await _notify_admins(db, incident)


async def _find_open_incident_sharing_server(
    db: AsyncSession, server_ids: set[int]
) -> Incident | None:
    """server_ids 중 하나라도 포함하는 OPEN 인시던트를 찾는다(없으면 None).

    server_ids 는 JSONB 리스트라 SQL 로 교집합을 보기 번거롭다. OPEN 인시던트 수는
    적으므로 파이썬에서 교집합을 확인한다(학부 수준 가독성 우선).
    """
    open_incidents = (
        await db.execute(
            select(Incident).where(Incident.status == IncidentStatus.OPEN.value)
        )
    ).scalars().all()
    for incident in open_incidents:
        if server_ids & set(incident.server_ids):
            return incident
    return None


def _merge_server_ids(existing: list[int], new: set[int]) -> list[int]:
    """기존 서버 목록에 새 서버 id 를 중복 없이 더한다(정렬해 안정적 순서 유지)."""
    return sorted(set(existing) | new)


async def _recompute_severity(db: AsyncSession, incident_id: int) -> str:
    """인시던트에 묶인 모든 이상을 근거로 심각도를 다시 계산한다.

    최고 편차는 |current_value - mean| / stddev 의 최댓값(stddev>0 인 것만).
    """
    anomalies = (
        await db.execute(
            select(AnomalyRecord).where(AnomalyRecord.incident_id == incident_id)
        )
    ).scalars().all()
    server_ids = {a.server_id for a in anomalies}
    deviations = [
        abs(a.current_value - a.mean) / a.stddev for a in anomalies if a.stddev > 0
    ]
    max_deviation = max(deviations) if deviations else 0.0
    return compute_severity(
        anomaly_count=len(anomalies),
        server_count=len(server_ids),
        max_deviation=max_deviation,
    )


async def _notify_admins(db: AsyncSession, incident: Incident) -> None:
    """ADM 사용자 각각에게 인시던트 알림 1건씩 만든다(인시던트당 1회)."""
    # 기존 인시던트에 이상이 더 부착될 때는 의도적으로 재알림하지 않는다
    # (노이즈 감소가 목적이라 인시던트당 알림은 한 번뿐이다).
    admins = (
        await db.execute(select(User).where(User.role == UserRole.ADM.value))
    ).scalars().all()
    for admin in admins:
        db.add(Notification(
            user_id=admin.id,
            type="INCIDENT",
            message=f"이상 {incident.anomaly_count}건이 인시던트로 묶였습니다.",
            payload={"incidentId": incident.id, "serverIds": incident.server_ids},
        ))


async def _auto_resolve_stale(db: AsyncSession, now: datetime) -> None:
    """묶인 이상의 최신 시각이 유휴 한계보다 오래된 OPEN 인시던트를 종료한다."""
    open_incidents = (
        await db.execute(
            select(Incident).where(Incident.status == IncidentStatus.OPEN.value)
        )
    ).scalars().all()
    for incident in open_incidents:
        latest = await db.scalar(
            select(func.max(AnomalyRecord.detected_at))
            .where(AnomalyRecord.incident_id == incident.id)
        )
        if latest is not None and latest < now - _AUTO_RESOLVE_IDLE:
            incident.status = IncidentStatus.RESOLVED.value
            incident.resolved_at = now
