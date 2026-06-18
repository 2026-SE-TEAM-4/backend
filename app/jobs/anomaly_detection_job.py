"""이상탐지 잡(F27, UC18).

5분 주기로 활성 서버의 최근 OK 메트릭을 메트릭별 시계열로 모아 기준선 위쪽 이탈을
판정하고, 이탈 시 AnomalyRecord 를 기록한다. 같은 서버·메트릭의 연속 기록은 디바운스로
억제한다.

단발성 튐(한 사이클만 잠깐 오른 값)은 무시한다 — 최근 연속 _SUSTAINED_SAMPLES 개
표본이 '모두' 기준선 밖일 때만 이상으로 본다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import AnomalyRecord, Server, ServerMetric
from app.models.enums import MetricStatus, MetricType
from app.services.anomaly import MIN_SAMPLES, evaluate_anomaly
from app.services.scheduler_log import add_scheduler_log

logger = logging.getLogger(__name__)

# 기준선 계산에 쓰는 과거 구간과 최대 표본 수.
_BASELINE_WINDOW = timedelta(days=7)
_MAX_SAMPLES = 1000
# 같은 서버·메트릭 이상은 이 시간 내 한 번만 기록(알림 폭주 방지).
_DEBOUNCE = timedelta(hours=1)
# 최근 연속 이만큼 표본이 모두 기준선 밖이어야 이상으로 본다(한 사이클 단발 튐 무시).
_SUSTAINED_SAMPLES = 2

# MetricType → ServerMetric 컬럼명.
_METRIC_ATTR = {
    MetricType.CPU: "cpu_usage",
    MetricType.MEM: "mem_usage",
    MetricType.NET: "net_usage",
    MetricType.GPU: "gpu_usage",
}


async def detect_anomalies(*, session_factory: async_sessionmaker = SessionLocal) -> None:
    """활성 서버별·메트릭별로 최신값이 기준선을 벗어났는지 판정한다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            servers = (
                await db.execute(select(Server).where(Server.deleted_at.is_(None)))
            ).scalars().all()
            recorded = 0
            for server in servers:
                recorded += await _detect_for_server(db, server.id, now)
            # 대시보드(F21)용 실행 이력: 이번에 기록한 이상 건수를 처리량으로 남긴다.
            add_scheduler_log(db, "UC18", recorded)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("이상탐지 잡 실패")


async def _detect_for_server(db: AsyncSession, server_id: int, now: datetime) -> int:
    """한 서버의 메트릭별 이상을 판정·기록하고, 이번에 기록한 이상 건수를 반환한다."""
    rows = (
        await db.execute(
            select(ServerMetric)
            .where(
                ServerMetric.server_id == server_id,
                ServerMetric.status == MetricStatus.OK.value,
                ServerMetric.collected_at >= now - _BASELINE_WINDOW,
            )
            .order_by(ServerMetric.collected_at.desc())
            .limit(_MAX_SAMPLES)
        )
    ).scalars().all()

    recorded = 0
    for metric, attr in _METRIC_ATTR.items():
        values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        if len(values) < MIN_SAMPLES + _SUSTAINED_SAMPLES:  # 최신 연속분 + 기준선 표본
            continue
        # rows 는 최신순이므로 values[:N] 이 가장 최근 연속 표본, 그 이전이 기준선.
        recent = values[:_SUSTAINED_SAMPLES]
        baseline = values[_SUSTAINED_SAMPLES:]
        decisions = [evaluate_anomaly(baseline, v) for v in recent]
        sustained = all(d.is_anomaly for d in decisions)
        if sustained and not await _recently_recorded(db, server_id, metric.value, now):
            latest, decision = recent[0], decisions[0]
            db.add(AnomalyRecord(
                server_id=server_id,
                metric=metric.value,
                current_value=latest,
                mean=decision.mean,
                stddev=decision.stddev,
            ))
            recorded += 1
            logger.info("이상 감지: 서버 %d %s 값 %.1f (연속 %d표본)", server_id, metric.value, latest, _SUSTAINED_SAMPLES)
    return recorded


async def _recently_recorded(db: AsyncSession, server_id: int, metric: str, now: datetime) -> bool:
    found = await db.scalar(
        select(func.count())
        .select_from(AnomalyRecord)
        .where(
            AnomalyRecord.server_id == server_id,
            AnomalyRecord.metric == metric,
            AnomalyRecord.detected_at >= now - _DEBOUNCE,
        )
    )
    return bool(found)
