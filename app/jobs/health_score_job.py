"""건강점수 산출 잡(F28, UC19).

10분 주기로 활성 서버의 최신 메트릭·최근 이상빈도·수집 누락률로 건강점수를 산출해
Server.health_score 에 반영한다. 즉시예약 선정(reservation_service)이 이 값으로 정렬한다.
같은 실행에서 시점별 점수를 ServerHealthHistory 에도 한 행 남겨, 장애 예측 잡(UC23)이
7일 추세 기울기를 낼 수 있게 한다.

낙관적 락 주의: Server.version 은 예약 흐름이 동시성 제어에 쓴다. 건강점수 갱신이
version 을 올리면 동시 예약 갱신과 불필요하게 충돌하므로, version 을 건드리지 않는
직접 UPDATE 로만 health_score 를 쓴다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import AnomalyRecord, Server, ServerHealthHistory, ServerMetric
from app.models.enums import MetricStatus
from app.services.health import compute_health_score
from app.services.scheduler_log import add_scheduler_log

logger = logging.getLogger(__name__)

_ANOMALY_WINDOW = timedelta(hours=24)
_MISSING_WINDOW = timedelta(hours=1)


async def compute_health_scores(*, session_factory: async_sessionmaker = SessionLocal) -> None:
    """활성 서버별 건강점수를 산출해 반영한다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            servers = (
                await db.execute(select(Server).where(Server.deleted_at.is_(None)))
            ).scalars().all()
            scored = 0
            for server in servers:
                score = await _score_for_server(db, server.id, now)
                if score is None:
                    continue
                # version 미변경 직접 UPDATE(낙관적 락 충돌 방지).
                await db.execute(
                    update(Server).where(Server.id == server.id).values(health_score=score)
                )
                # 추세(7일 기울기) 계산을 위해 시점별 점수 이력도 함께 남긴다(UC23).
                # Server.health_score 는 최신값만 들고 있어 추세를 낼 수 없기 때문이다.
                db.add(ServerHealthHistory(server_id=server.id, score=score))
                scored += 1
            # 대시보드(F21)용 실행 이력: 이번에 점수를 산출한 서버 수를 처리량으로 남긴다.
            add_scheduler_log(db, "UC19", scored)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("건강점수 잡 실패")


async def _score_for_server(db: AsyncSession, server_id: int, now: datetime) -> int | None:
    latest = await db.scalar(
        select(ServerMetric)
        .where(ServerMetric.server_id == server_id, ServerMetric.status == MetricStatus.OK.value)
        .order_by(ServerMetric.collected_at.desc())
        .limit(1)
    )
    if latest is None:  # 측정값이 없으면 점수를 만들지 않는다.
        return None

    anomaly_count = await _count(db, AnomalyRecord, AnomalyRecord.server_id == server_id,
                                 AnomalyRecord.detected_at >= now - _ANOMALY_WINDOW)
    total = await _count(db, ServerMetric, ServerMetric.server_id == server_id,
                         ServerMetric.collected_at >= now - _MISSING_WINDOW)
    missing = await _count(db, ServerMetric, ServerMetric.server_id == server_id,
                           ServerMetric.status == MetricStatus.MISSING.value,
                           ServerMetric.collected_at >= now - _MISSING_WINDOW)
    missing_rate = missing / total if total else 0.0

    return compute_health_score(
        cpu_usage=latest.cpu_usage,
        mem_usage=latest.mem_usage,
        gpu_usage=latest.gpu_usage,
        anomaly_count_24h=anomaly_count,
        missing_rate_1h=missing_rate,
    )


async def _count(db: AsyncSession, model, *conditions) -> int:
    """주어진 조건(2~3개)을 만족하는 model 행 수를 센다. 없으면 0."""
    return await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
