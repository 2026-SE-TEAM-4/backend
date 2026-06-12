"""장애·건강 열화 예측 잡(F32, UC23).

10분 주기(건강점수 잡 직후)로 활성 서버마다 최근 7일 건강점수 이력의 기울기, 최근 24h
이상 빈도, 현재 건강점수로 위험도(risk_score)와 위험 진입 예상 시각(eta_to_risk)을
산출해 Server 에 반영한다. 위험이 임계 이상이면 ADM 에게 점검 권고 알림을 보낸다.

낙관적 락 주의: 건강점수 잡과 같은 이유로 risk_score·eta_to_risk 는 version 을 건드리지
않는 직접 UPDATE 로만 쓴다(동시 예약 갱신과 불필요한 충돌 방지).

무거운 점수화 로직은 순수 로직(services/failure_prediction.py)으로 분리하고, 잡은 DB
입출력과 알림만 담당한다. 한 서버의 실패가 전체 잡을 멈추지 않게 서버 단위로 격리한다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import (
    AnomalyRecord,
    Notification,
    Server,
    ServerHealthHistory,
    User,
)
from app.models.enums import UserRole
from app.services.failure_prediction import (
    compute_risk_score,
    estimate_eta_to_risk,
    ewma_slope,
    risk_drivers,
)

logger = logging.getLogger(__name__)

# 추세 기울기를 보는 과거 구간과 이상 빈도를 세는 윈도우.
_HISTORY_WINDOW = timedelta(days=7)
_ANOMALY_WINDOW = timedelta(hours=24)

# 위험도가 이 값 이상이면 ADM 에게 점검 권고 알림을 보낸다(0~100).
_RISK_THRESHOLD = 50.0

# 건강점수가 이 값으로 떨어지면 위험으로 본다(eta_to_risk 외삽 기준).
_DANGER_HEALTH = 50


async def predict_failures(*, session_factory: async_sessionmaker = SessionLocal) -> None:
    """활성 서버별 위험도·위험 진입 시각을 산출·반영하고, 고위험은 ADM 에게 알린다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            servers = (
                await db.execute(select(Server).where(Server.deleted_at.is_(None)))
            ).scalars().all()
            for server in servers:
                await _predict_one_server(db, server, now)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("장애 예측 잡 실패")


async def _predict_one_server(db: AsyncSession, server: Server, now: datetime) -> None:
    """한 서버의 위험도·위험 진입 시각을 산출해 반영하고, 고위험이면 알림을 만든다."""
    history = await _health_history(db, server.id, now)
    slope = ewma_slope(history)
    anomaly_count = await _anomaly_count_24h(db, server.id, now)

    risk = compute_risk_score(
        health_slope=slope,
        anomaly_count_24h=anomaly_count,
        current_health=server.health_score,
    )
    eta = estimate_eta_to_risk(
        now=now,
        current_health=server.health_score,
        health_slope=slope,
        danger_health=_DANGER_HEALTH,
    )

    # version 미변경 직접 UPDATE(낙관적 락 충돌 방지). health_score 잡과 같은 규칙.
    await db.execute(
        update(Server).where(Server.id == server.id).values(risk_score=risk, eta_to_risk=eta)
    )

    if risk >= _RISK_THRESHOLD:
        drivers = risk_drivers(
            health_slope=slope,
            anomaly_count_24h=anomaly_count,
            current_health=server.health_score,
        )
        await _notify_admins_of_risk(db, server, risk, eta, drivers)


async def _health_history(
    db: AsyncSession, server_id: int, now: datetime
) -> list[tuple[datetime, float]]:
    """최근 7일 건강점수 이력을 (시각, 점수) 쌍의 시간순 목록으로 읽는다."""
    rows = (
        await db.execute(
            select(ServerHealthHistory.recorded_at, ServerHealthHistory.score)
            .where(
                ServerHealthHistory.server_id == server_id,
                ServerHealthHistory.recorded_at >= now - _HISTORY_WINDOW,
            )
            .order_by(ServerHealthHistory.recorded_at)
        )
    ).all()
    return [(row[0], float(row[1])) for row in rows]


async def _anomaly_count_24h(db: AsyncSession, server_id: int, now: datetime) -> int:
    """최근 24h 동안 이 서버에 기록된 이상 건수를 센다."""
    count = await db.scalar(
        select(func.count())
        .select_from(AnomalyRecord)
        .where(
            AnomalyRecord.server_id == server_id,
            AnomalyRecord.detected_at >= now - _ANOMALY_WINDOW,
        )
    )
    return count or 0


async def _notify_admins_of_risk(
    db: AsyncSession,
    server: Server,
    risk: float,
    eta: datetime | None,
    drivers: list[str],
) -> None:
    """ADM 사용자 각각에게 장애 예측 알림 1건씩 만든다(점검 권고 포함).

    점검 권고는 알림 메시지로만 전한다. 일부러 MaintenanceSchedule 행을 만들지 않는데,
    예측 잡이 서버 상태(점검창)에 부수효과를 내면 안 되고, 점검창 생성은 운영자가
    판단해 직접 하도록 두기 위함이다(자동 조치 금지, 사람 검토).
    """
    eta_text = eta.isoformat() if eta is not None else None
    admins = (
        await db.execute(select(User).where(User.role == UserRole.ADM.value))
    ).scalars().all()
    for admin in admins:
        db.add(Notification(
            user_id=admin.id,
            type="PREDICTIVE_FAILURE",
            message=f"서버 {server.id}의 장애 위험이 높습니다(위험도 {round(risk)}). 점검을 권고합니다.",
            payload={
                "serverId": server.id,
                "riskScore": risk,
                "etaToRisk": eta_text,
                "drivers": drivers,
            },
        ))
