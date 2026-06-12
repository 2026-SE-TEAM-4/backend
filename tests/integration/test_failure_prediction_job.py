"""장애·건강 열화 예측 잡 통합 테스트(F32/UC23, Postgres 컨테이너 필요).

- 열화 서버(7일 하락 이력 + 최근 이상): risk_score·eta_to_risk 가 채워지고, version 은
  변하지 않으며, ADM 에게 PREDICTIVE_FAILURE 알림이 생긴다.
- 건강·개선 서버: 위험이 낮고 eta 는 None, 알림이 생기지 않는다.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.database import Base
from app.jobs.failure_prediction_job import predict_failures
from app.models import (
    AnomalyRecord,
    Notification,
    Server,
    ServerHealthHistory,
    Team,
    User,
)

pytestmark = pytest.mark.integration


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


def _server(server_id: int, *, health_score: int) -> Server:
    return Server(id=server_id, name=f"s{server_id}", ip=f"10.0.0.{server_id}",
                  cpu_cores=8, ram_gb=32, health_score=health_score)


def _admin(user_id: int) -> User:
    return User(id=user_id, name="adm", email=f"adm{user_id}@b.com",
                role="ADM", team_id=1)


async def _seed_declining_history(db, server_id: int, *, now: datetime) -> None:
    # 7일에 걸쳐 90 → 40 으로 하루 약 -8 점씩 떨어지는 건강점수 이력.
    scores = [90, 82, 74, 66, 58, 50, 40]
    for day_offset, score in enumerate(reversed(scores)):
        recorded_at = now - timedelta(days=day_offset)
        db.add(ServerHealthHistory(server_id=server_id, score=score, recorded_at=recorded_at))


async def _seed_rising_history(db, server_id: int, *, now: datetime) -> None:
    # 7일에 걸쳐 꾸준히 개선되는 이력(열화 아님).
    scores = [60, 66, 72, 78, 84, 90, 96]
    for day_offset, score in enumerate(reversed(scores)):
        recorded_at = now - timedelta(days=day_offset)
        db.add(ServerHealthHistory(server_id=server_id, score=score, recorded_at=recorded_at))


async def test_declining_server_gets_risk_and_admin_notification(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Team(id=1, name="Lab", code="LAB", total_quota_limit=10))
        db.add(_server(1, health_score=40))
        db.add(_admin(100))
        await db.flush()  # 팀·서버·사용자 먼저 적재(이력·이상·알림의 FK 대상)
        await _seed_declining_history(db, 1, now=now)
        # 최근 24h 이상 여러 건 → 위험 가중.
        for _ in range(5):
            db.add(AnomalyRecord(server_id=1, metric="CPU", current_value=99.0,
                                 mean=50.0, stddev=10.0))
        await db.commit()

    await predict_failures(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 1)
        notifications = (await db.execute(select(Notification))).scalars().all()

    assert server.risk_score is not None and server.risk_score > 0
    assert server.eta_to_risk is None or isinstance(server.eta_to_risk, datetime)
    assert server.version == 1  # 위험도 갱신이 낙관적 락을 건드리지 않는다
    assert len(notifications) == 1
    assert notifications[0].type == "PREDICTIVE_FAILURE"
    assert notifications[0].payload["serverId"] == 1
    assert notifications[0].payload["drivers"]  # 근거 문구가 비어 있지 않다


async def test_eta_is_set_when_declining_above_danger(factory):
    # 현재 건강이 위험 임계(50)보다 높고 열화 중이면 eta_to_risk 가 외삽된다.
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(_server(1, health_score=80))
        await db.flush()
        await _seed_declining_history(db, 1, now=now)
        await db.commit()

    await predict_failures(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 1)
    assert server.eta_to_risk is not None
    assert server.eta_to_risk > now  # 위험 진입은 미래 시점이다


async def _seed_flat_history(db, server_id: int, *, score: int, now: datetime) -> None:
    # 7일간 같은 점수로 평탄한 이력(기울기 0 → 위험에 하락 가중이 없다).
    for day_offset in range(7):
        recorded_at = now - timedelta(days=day_offset)
        db.add(ServerHealthHistory(server_id=server_id, score=score, recorded_at=recorded_at))


async def test_risk_just_below_threshold_sends_no_notification(factory):
    # 평탄 이력·이상 없음·건강 51 → 위험은 (100-51)=49 로 임계(50) 바로 아래.
    # 알림 임계 경계를 못 박는다: 49 에서는 ADM 알림이 생기지 않아야 한다.
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Team(id=1, name="Lab", code="LAB", total_quota_limit=10))
        db.add(_server(3, health_score=51))
        db.add(_admin(102))
        await db.flush()
        await _seed_flat_history(db, 3, score=51, now=now)
        await db.commit()

    await predict_failures(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 3)
        notifications = (await db.execute(select(Notification))).scalars().all()

    assert server.risk_score == 49.0
    assert notifications == []  # 임계(50) 미만이므로 알림이 없어야 한다


async def test_healthy_improving_server_has_low_risk_and_no_notification(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Team(id=1, name="Lab", code="LAB", total_quota_limit=10))
        db.add(_server(2, health_score=96))
        db.add(_admin(101))
        await db.flush()
        await _seed_rising_history(db, 2, now=now)
        await db.commit()

    await predict_failures(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 2)
        notifications = (await db.execute(select(Notification))).scalars().all()

    # 개선 중·이상 없음·건강 높음 → 위험은 낮다(현재건강 96 의 (100-96) 항만 약간 남는다).
    assert server.risk_score is not None and server.risk_score < 50.0
    assert server.eta_to_risk is None  # 열화가 아니므로 위험 진입 시점이 없다
    assert server.version == 1
    assert notifications == []  # 고위험이 아니므로 알림을 만들지 않는다
