"""용량·수요 예측 잡 통합 테스트(UC22, Postgres 컨테이너 필요).

- 상승 추세의 시간 간격 OK 메트릭 → horizon 이 채워진 Forecast 생성
- 임박 포화가 예측되면 ADM 사용자에게 CAPACITY 알림 1건
- 낮고 평평한 시계열 → saturation_at 이 NULL 인 Forecast
- 예약 몇 건 → server_id 가 NULL 인 RESERVATION_DEMAND 예측
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.jobs.forecast_job as forecast_job
import app.models  # noqa: F401  메타데이터 등록
from app.database import Base
from app.jobs.forecast_job import generate_forecasts
from app.models import Forecast, Notification, Reservation, Server, Team, User
from app.services.forecast import forecast_series as real_forecast_series

pytestmark = pytest.mark.integration

# 10일치 시간 간격 표본. MIN_SAMPLES(48)를 넉넉히 넘으면서 시드가 가볍다.
_HOURS = 24 * 10


@pytest_asyncio.fixture
async def factory(containers):
    postgres, _ = containers
    engine = create_async_engine(postgres.get_connection_url())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _server(server_id: int) -> Server:
    return Server(id=server_id, name=f"s{server_id}", ip=f"10.0.0.{server_id}",
                  cpu_cores=8, ram_gb=32)


def _metric_rows(server_id: int, *, base: float, slope: float, now: datetime) -> list:
    """server_id 에 대해 _HOURS 개의 OK 메트릭을 시간 간격으로 만든다.

    cpu_usage = base + slope*시간 으로 두어 slope>0 이면 상승 추세를 만든다.
    예측 입력은 cpu_usage 시계열이고, mem/gpu 는 평탄히 둔다(여기선 CPU 만 검증).
    """
    from app.models import ServerMetric

    rows = []
    for hour in range(_HOURS):
        collected_at = now - timedelta(hours=_HOURS - hour)
        rows.append(ServerMetric(
            server_id=server_id,
            cpu_usage=base + slope * hour,
            mem_usage=30.0,
            net_usage=10.0,
            gpu_usage=None,  # GPU 미탑재 → GPU 예측은 표본이 없어 건너뛴다.
            status="OK",
            collected_at=collected_at,
        ))
    return rows


async def test_rising_metric_produces_forecast_and_capacity_notification(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Team(id=1, name="Lab", code="LAB", total_quota_limit=10))
        db.add(User(id=1, name="adm", email="adm@b.com", role="ADM", team_id=1))
        db.add(_server(1))
        await db.flush()  # 서버 먼저 적재(메트릭의 FK 대상)
        # base 70 에서 시간당 0.2 씩 올라 10일 뒤 약 118 → 7일 예측 구간에서 90 돌파.
        db.add_all(_metric_rows(1, base=70.0, slope=0.2, now=now))
        await db.commit()

    await generate_forecasts(session_factory=factory)

    async with factory() as db:
        cpu_forecast = (
            await db.execute(
                select(Forecast).where(Forecast.server_id == 1, Forecast.metric == "CPU")
            )
        ).scalars().one()
        notifications = (
            await db.execute(select(Notification).where(Notification.type == "CAPACITY"))
        ).scalars().all()

    assert len(cpu_forecast.horizon) > 0
    assert cpu_forecast.saturation_at is not None
    # 임박 포화(72h 내)면 ADM 에게 CAPACITY 알림 1건.
    assert len(notifications) == 1
    assert notifications[0].user_id == 1
    assert notifications[0].payload["serverId"] == 1
    assert notifications[0].payload["metric"] == "CPU"


async def test_flat_low_metric_has_no_saturation(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(_server(2))
        await db.flush()
        # 낮은 수준(20%)에서 거의 변화 없음 → 포화 없음.
        db.add_all(_metric_rows(2, base=20.0, slope=0.0, now=now))
        await db.commit()

    await generate_forecasts(session_factory=factory)

    async with factory() as db:
        cpu_forecast = (
            await db.execute(
                select(Forecast).where(Forecast.server_id == 2, Forecast.metric == "CPU")
            )
        ).scalars().one()
        notifications = (
            await db.execute(select(Notification).where(Notification.type == "CAPACITY"))
        ).scalars().all()

    assert cpu_forecast.saturation_at is None
    assert notifications == []


async def test_reservations_produce_pool_wide_demand_forecast(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Team(id=1, name="Lab", code="LAB", total_quota_limit=10))
        db.add(User(id=1, name="stu", email="stu@b.com", role="STU", team_id=1))
        db.add(_server(3))
        await db.flush()
        # 10일에 걸쳐 시간마다 예약 1건씩 → 수요 시계열 표본이 충분해진다.
        for hour in range(_HOURS):
            created_at = now - timedelta(hours=_HOURS - hour)
            db.add(Reservation(
                user_id=1, server_id=3,
                start_time=created_at, end_time=created_at + timedelta(hours=1),
                status="RESERVED", created_at=created_at,
            ))
        await db.commit()

    await generate_forecasts(session_factory=factory)

    async with factory() as db:
        demand = (
            await db.execute(
                select(Forecast).where(Forecast.metric == "RESERVATION_DEMAND")
            )
        ).scalars().one()

    assert demand.server_id is None
    assert len(demand.horizon) > 0
    assert demand.saturation_at is None  # 수요에는 포화 개념이 없다.


async def test_one_failing_server_does_not_block_others(factory, monkeypatch):
    # 한 서버의 적합이 실패해도 다른 서버 예측은 계속 저장되어야 한다(잡 격리).
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add_all([_server(10), _server(11)])
        await db.flush()
        db.add_all(_metric_rows(10, base=70.0, slope=0.2, now=now))
        db.add_all(_metric_rows(11, base=20.0, slope=0.0, now=now))
        await db.commit()

    # 서버 10 의 시계열에 대해서만 실제 statsmodels 실패를 흉내 내 ValueError 를 던진다.
    failing_base = 70.0

    def fake_forecast_series(series, **kwargs):
        if float(series.iloc[0]) >= failing_base:
            raise ValueError("적합 실패 흉내")
        return real_forecast_series(series, **kwargs)

    monkeypatch.setattr(forecast_job, "forecast_series", fake_forecast_series)

    await generate_forecasts(session_factory=factory)

    async with factory() as db:
        failed = (
            await db.execute(
                select(Forecast).where(Forecast.server_id == 10, Forecast.metric == "CPU")
            )
        ).scalars().all()
        survived = (
            await db.execute(
                select(Forecast).where(Forecast.server_id == 11, Forecast.metric == "CPU")
            )
        ).scalars().all()

    # 실패한 서버는 저장되지 않고, 정상 서버는 그대로 저장된다.
    assert failed == []
    assert len(survived) == 1


async def test_demand_handles_trailing_zero_hours(factory):
    # 예약이 존재하다가 now 이전에 끊겨도(최근 0수요 구간), 수요 예측이 생성·저장되어야 한다.
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Team(id=1, name="Lab", code="LAB", total_quota_limit=10))
        db.add(User(id=1, name="stu", email="stu@b.com", role="STU", team_id=1))
        db.add(_server(20))
        await db.flush()
        # 30일 전부터 약 7일 전까지만 예약이 있고, 최근 7일(168시간)은 예약이 없다.
        recent_gap_hours = 24 * 7
        for hour in range(_HOURS):
            if hour >= _HOURS - recent_gap_hours:
                continue  # 최근 구간은 의도적으로 비워 trailing 0수요를 만든다.
            created_at = now - timedelta(hours=_HOURS - hour)
            db.add(Reservation(
                user_id=1, server_id=20,
                start_time=created_at, end_time=created_at + timedelta(hours=1),
                status="RESERVED", created_at=created_at,
            ))
        await db.commit()

    await generate_forecasts(session_factory=factory)

    async with factory() as db:
        demand = (
            await db.execute(
                select(Forecast).where(Forecast.metric == "RESERVATION_DEMAND")
            )
        ).scalars().one()

    assert demand.server_id is None
    assert len(demand.horizon) > 0
