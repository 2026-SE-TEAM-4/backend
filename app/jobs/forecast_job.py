"""용량·수요 예측 잡(F31, UC22).

1시간 주기로 활성 서버의 최근 30일 사용률(CPU/MEM/GPU)을 시간 단위로 모아 Holt-Winters 로
향후 7일을 예측하고 Forecast 행으로 저장한다. 포화가 72시간 안으로 예상되면 ADM 에게
CAPACITY 알림을 보낸다. 풀 전체 예약 수요(Reservation.created_at 추이)도 같은 방식으로
예측해 server_id=NULL 로 저장한다.

무거운 적합(statsmodels)은 순수 로직(services/forecast.py)으로 분리하고, 잡은 DB 입출력과
시계열 준비(리샘플·보간)만 담당한다. 데이터가 부족한 서버·메트릭은 조용히 건너뛴다.
"""

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import Forecast, Notification, Reservation, Server, ServerMetric, User
from app.models.enums import ForecastMetric, MetricStatus, UserRole
from app.services.forecast import InsufficientHistoryError, forecast_series

logger = logging.getLogger(__name__)

# 예측에 쓰는 과거 구간. 학기 단위 데이터에서도 추세·계절을 잡을 만큼 길게 둔다.
_HISTORY_WINDOW = timedelta(days=30)
# 이 시간 안에 포화가 예상되면 운영자에게 미리 알린다.
_NEAR_SATURATION = timedelta(hours=72)

# ForecastMetric(서버 사용률) → ServerMetric 컬럼명. 예약 수요는 별도로 처리한다.
_METRIC_ATTR = {
    ForecastMetric.CPU: "cpu_usage",
    ForecastMetric.MEM: "mem_usage",
    ForecastMetric.GPU: "gpu_usage",
}


async def generate_forecasts(*, session_factory: async_sessionmaker = SessionLocal) -> None:
    """활성 서버별 사용률과 풀 전체 예약 수요를 예측해 저장한다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            servers = (
                await db.execute(select(Server).where(Server.deleted_at.is_(None)))
            ).scalars().all()
            for server in servers:
                for metric, attr in _METRIC_ATTR.items():
                    await _forecast_server_metric(db, server.id, metric, attr, now)
            await _forecast_reservation_demand(db, now)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("용량·수요 예측 잡 실패")


async def _forecast_server_metric(
    db: AsyncSession, server_id: int, metric: ForecastMetric, attr: str, now: datetime
) -> None:
    """한 서버·메트릭의 사용률을 예측해 저장하고, 임박 포화면 ADM 에게 알린다."""
    rows = (
        await db.execute(
            select(ServerMetric.collected_at, getattr(ServerMetric, attr))
            .where(
                ServerMetric.server_id == server_id,
                ServerMetric.status == MetricStatus.OK.value,
                ServerMetric.collected_at >= now - _HISTORY_WINDOW,
                getattr(ServerMetric, attr).is_not(None),  # GPU 미탑재 노드의 NULL 제외
            )
            .order_by(ServerMetric.collected_at)
        )
    ).all()

    series = _to_hourly_series(rows)
    if series is None:
        return  # 표본이 거의 없으면 시계열을 만들지 않는다.

    try:
        result = forecast_series(series)
    except InsufficientHistoryError:
        return  # 적합에 필요한 최소 표본 미만 → 조용히 건너뛴다.

    saturation_at = _parse_iso(result.saturation_at)
    db.add(Forecast(
        server_id=server_id,
        metric=metric.value,
        horizon=result.horizon,
        saturation_at=saturation_at,
        confidence=result.confidence,
    ))

    if saturation_at is not None and saturation_at - now <= _NEAR_SATURATION:
        await _notify_admins_of_saturation(db, server_id, metric.value, saturation_at)


async def _forecast_reservation_demand(db: AsyncSession, now: datetime) -> None:
    """풀 전체 예약 생성 추이를 예측해 server_id=NULL 로 저장한다.

    예약 수요에는 사용률 포화 임계가 의미 없으므로 saturation_at 은 항상 NULL 로 둔다.
    """
    rows = (
        await db.execute(
            select(Reservation.created_at)
            .where(Reservation.created_at >= now - _HISTORY_WINDOW)
            .order_by(Reservation.created_at)
        )
    ).all()

    series = _to_hourly_count_series(rows)
    if series is None:
        return

    try:
        result = forecast_series(series)
    except InsufficientHistoryError:
        return

    db.add(Forecast(
        server_id=None,
        metric=ForecastMetric.RESERVATION_DEMAND.value,
        horizon=result.horizon,
        saturation_at=None,  # 예약 수요는 포화 개념이 없다.
        confidence=result.confidence,
    ))


def _to_hourly_series(rows: list) -> pd.Series | None:
    """(collected_at, value) 행들을 1시간 평균 시계열로 만든다. 비면 None.

    1분 간격 수집을 1시간 평균으로 리샘플하고, 중간 결측은 선형 보간한다.
    예측 함수가 균일 간격 시계열을 기대하기 때문이다.
    """
    if not rows:
        return None
    index = pd.DatetimeIndex([row[0] for row in rows])
    values = [float(row[1]) for row in rows]
    series = pd.Series(values, index=index).resample("1h").mean().interpolate()
    return series if not series.empty else None


def _to_hourly_count_series(rows: list) -> pd.Series | None:
    """(created_at,) 행들을 시간당 예약 생성 건수 시계열로 만든다. 비면 None.

    수요는 "건수"라 합(개수)으로 리샘플한다. 예약이 없던 시간은 0 으로 채운다.
    """
    if not rows:
        return None
    index = pd.DatetimeIndex([row[0] for row in rows])
    counts = pd.Series(1.0, index=index).resample("1h").sum().fillna(0.0)
    return counts if not counts.empty else None


async def _notify_admins_of_saturation(
    db: AsyncSession, server_id: int, metric: str, saturation_at: datetime
) -> None:
    """ADM 사용자 각각에게 임박 포화 알림 1건씩 만든다."""
    admins = (
        await db.execute(select(User).where(User.role == UserRole.ADM.value))
    ).scalars().all()
    for admin in admins:
        db.add(Notification(
            user_id=admin.id,
            type="CAPACITY",
            message=f"서버 {server_id}의 {metric} 사용률이 곧 포화될 것으로 예측됩니다.",
            payload={
                "serverId": server_id,
                "metric": metric,
                "saturationAt": saturation_at.isoformat(),
            },
        ))


def _parse_iso(ts: str | None) -> datetime | None:
    """예측이 ISO 문자열로 준 포화 시각을 datetime 으로 되돌린다. None 은 그대로."""
    return datetime.fromisoformat(ts) if ts is not None else None
