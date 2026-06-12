"""유휴 서버 자동 회수 잡 통합 테스트(F24/UC15, Postgres 컨테이너 필요).

2단계 경고-회수 흐름을 검증한다:
- 유휴인데 경고가 없으면 → IDLE_WARNING 1건 발송, 회수는 안 함
- 유휴이고 경고가 유예(15분)보다 오래됐으면 → 회수(예약 RECLAIMED, 서버 AVAILABLE,
  Quota.used 감소, RECLAIM 알림)
- 유휴가 아니면 아무것도 안 함
- 경고가 아직 유예 안에 있으면 회수하지 않음(재경고도 안 함)
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.database import Base
from app.jobs.idle_reclaim_job import reclaim_idle_servers
from app.models import (
    Notification,
    Quota,
    Reservation,
    SchedulerLog,
    Server,
    ServerMetric,
    Team,
    User,
)
from app.models.enums import ReservationStatus, ServerStatus

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


async def _seed_base(db) -> None:
    """팀·사용자·서버(IN_USE)·사용 중 예약·한도를 깔아 점유 상태를 만든다.

    모델에 ORM relationship 이 없어 같은 flush 안에서 부모-자식 INSERT 순서가
    보장되지 않는다. 부모(팀·사용자·서버)를 먼저 flush 한 뒤 자식(예약·한도)을
    추가해 FK 위반을 피한다.
    """
    db.add(Team(id=1, name="Lab-A", code="LAB-A", total_quota_limit=10))
    db.add(User(id=1, email="u1@example.com", role="STU", name="u1", team_id=1))
    db.add(Server(id=1, name="s1", ip="10.0.0.1", cpu_cores=8, ram_gb=32,
                  status=ServerStatus.IN_USE.value, version=1))
    await db.flush()
    now = datetime.now(tz=timezone.utc)
    db.add(Reservation(id=1, user_id=1, server_id=1,
                       start_time=now - timedelta(hours=1),
                       end_time=now + timedelta(hours=1),
                       status=ReservationStatus.IN_USE.value))
    db.add(Quota(id=1, user_id=1, team_id=1, limit=10, used=1, version=1))
    await db.flush()


def _seed_metrics(db, *, cpu: float) -> None:
    """최근 30분 구간에 OK 메트릭 몇 개를 넣어 평균 CPU 를 cpu 로 만든다."""
    now = datetime.now(tz=timezone.utc)
    for i in range(5):
        db.add(ServerMetric(server_id=1, cpu_usage=cpu, mem_usage=10.0, net_usage=1.0,
                            gpu_usage=None, status="OK",
                            collected_at=now - timedelta(minutes=i * 5)))


async def test_idle_without_warning_sends_warning_only(factory):
    async with factory() as db:
        await _seed_base(db)
        _seed_metrics(db, cpu=1.0)  # 유휴(임계 5% 미만)
        await db.commit()

    await reclaim_idle_servers(session_factory=factory)

    async with factory() as db:
        notifications = (await db.execute(select(Notification))).scalars().all()
        reservation = await db.get(Reservation, 1)
        server = await db.get(Server, 1)
    assert len(notifications) == 1
    assert notifications[0].type == "IDLE_WARNING"
    assert reservation.status == ReservationStatus.IN_USE.value  # 아직 회수 안 함
    assert server.status == ServerStatus.IN_USE.value


async def test_idle_with_aged_warning_reclaims(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        await _seed_base(db)
        _seed_metrics(db, cpu=1.0)  # 유휴 지속
        # 유예(15분)보다 오래된 경고를 직접 심어 2단계(회수)를 유도한다.
        db.add(Notification(user_id=1, type="IDLE_WARNING", message="warn",
                            payload={"serverId": 1, "reservationId": 1},
                            created_at=now - timedelta(minutes=20)))
        await db.commit()

    await reclaim_idle_servers(session_factory=factory)

    async with factory() as db:
        reservation = await db.get(Reservation, 1)
        server = await db.get(Server, 1)
        quota = await db.get(Quota, 1)
        reclaim = (await db.execute(
            select(Notification).where(Notification.type == "RECLAIM")
        )).scalars().all()
    assert reservation.status == ReservationStatus.RECLAIMED.value
    assert server.status == ServerStatus.AVAILABLE.value
    assert server.version == 2  # 상태 전이로 version 증가
    assert quota.used == 0  # 한도 사용량 1 → 0
    assert len(reclaim) == 1


async def test_not_idle_does_nothing(factory):
    async with factory() as db:
        await _seed_base(db)
        _seed_metrics(db, cpu=50.0)  # 사용 중(유휴 아님)
        await db.commit()

    await reclaim_idle_servers(session_factory=factory)

    async with factory() as db:
        notifications = (await db.execute(select(Notification))).scalars().all()
        reservation = await db.get(Reservation, 1)
    assert notifications == []
    assert reservation.status == ReservationStatus.IN_USE.value


async def test_recent_warning_within_grace_does_not_reclaim(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        await _seed_base(db)
        _seed_metrics(db, cpu=1.0)
        # 유예 안(5분 전)의 경고면 아직 회수하지 않는다.
        db.add(Notification(user_id=1, type="IDLE_WARNING", message="warn",
                            payload={"serverId": 1, "reservationId": 1},
                            created_at=now - timedelta(minutes=5)))
        await db.commit()

    await reclaim_idle_servers(session_factory=factory)

    async with factory() as db:
        reservation = await db.get(Reservation, 1)
        warnings = (await db.execute(
            select(Notification).where(Notification.type == "IDLE_WARNING")
        )).scalars().all()
        reclaim = (await db.execute(
            select(Notification).where(Notification.type == "RECLAIM")
        )).scalars().all()
    assert reservation.status == ReservationStatus.IN_USE.value
    assert len(warnings) == 1  # 재경고하지 않는다
    assert reclaim == []


async def test_reclaim_job_writes_scheduler_log(factory):
    # 회수 잡이 성공 실행되면 대시보드(F21)용 SchedulerLog(UC15) 한 행을 남긴다.
    # processed 는 이번 실행에서 실제로 회수한 서버 수(여기선 1)와 같다.
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        await _seed_base(db)
        _seed_metrics(db, cpu=1.0)
        db.add(Notification(user_id=1, type="IDLE_WARNING", message="warn",
                            payload={"serverId": 1, "reservationId": 1},
                            created_at=now - timedelta(minutes=20)))
        await db.commit()

    await reclaim_idle_servers(session_factory=factory)

    async with factory() as db:
        logs = (
            await db.execute(select(SchedulerLog).where(SchedulerLog.uc_id == "UC15"))
        ).scalars().all()
    assert len(logs) == 1
    assert logs[0].success is True
    assert logs[0].processed_count == 1
