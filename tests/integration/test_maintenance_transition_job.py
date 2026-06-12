"""점검 스케줄 자동 상태 전환 잡 통합 테스트(F30/UC13, Postgres 컨테이너 필요).

- start_at 도래 + 서버가 MAINTENANCE 아님 → MAINTENANCE(version+1)
- end_at 경과 + 서버가 MAINTENANCE → AVAILABLE(version+1)
- 아직 시작 전이거나 이미 같은 상태면 그대로(불필요한 version 증가 없음)
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.database import Base
from app.jobs.maintenance_transition_job import transition_maintenance_schedules
from app.models import MaintenanceSchedule, SchedulerLog, Server, Team, User
from sqlalchemy import select
from app.models.enums import ServerStatus

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


def _server(server_id: int, *, status: ServerStatus) -> Server:
    return Server(id=server_id, name=f"s{server_id}", ip=f"10.0.0.{server_id}",
                  cpu_cores=8, ram_gb=32, status=status.value, version=1)


def _seed_admin(db) -> None:
    # 점검 일정의 created_by FK 를 채우기 위한 최소 팀·사용자.
    db.add(Team(id=1, name="Lab-A", code="LAB-A", total_quota_limit=10))
    db.add(User(id=1, email="adm@example.com", role="ADM", name="adm", team_id=1))


def _schedule(server_id: int, *, start_at: datetime, end_at: datetime) -> MaintenanceSchedule:
    return MaintenanceSchedule(server_id=server_id, start_at=start_at, end_at=end_at,
                               created_by=1)


async def test_starts_maintenance_when_window_active(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        _seed_admin(db)
        db.add(_server(1, status=ServerStatus.AVAILABLE))
        await db.flush()  # 서버·사용자를 먼저 적재해 점검 일정 FK 를 만족시킨다
        db.add(_schedule(1, start_at=now - timedelta(minutes=5),
                         end_at=now + timedelta(hours=1)))
        await db.commit()

    await transition_maintenance_schedules(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 1)
    assert server.status == ServerStatus.MAINTENANCE.value
    assert server.version == 2  # 상태 전이이므로 version 을 올린다


async def test_ends_maintenance_when_window_passed(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        _seed_admin(db)
        db.add(_server(1, status=ServerStatus.MAINTENANCE))
        await db.flush()  # 서버·사용자를 먼저 적재해 점검 일정 FK 를 만족시킨다
        db.add(_schedule(1, start_at=now - timedelta(hours=2),
                         end_at=now - timedelta(minutes=5)))
        await db.commit()

    await transition_maintenance_schedules(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 1)
    assert server.status == ServerStatus.AVAILABLE.value
    assert server.version == 2


async def test_does_nothing_before_window_starts(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        _seed_admin(db)
        db.add(_server(1, status=ServerStatus.AVAILABLE))
        await db.flush()  # 서버·사용자를 먼저 적재해 점검 일정 FK 를 만족시킨다
        db.add(_schedule(1, start_at=now + timedelta(hours=1),
                         end_at=now + timedelta(hours=2)))
        await db.commit()

    await transition_maintenance_schedules(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 1)
    assert server.status == ServerStatus.AVAILABLE.value
    assert server.version == 1  # 아직 시작 전이라 전이 없음


async def test_active_window_does_not_rebump_when_already_maintenance(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        _seed_admin(db)
        db.add(_server(1, status=ServerStatus.MAINTENANCE))
        await db.flush()  # 서버·사용자를 먼저 적재해 점검 일정 FK 를 만족시킨다
        db.add(_schedule(1, start_at=now - timedelta(minutes=5),
                         end_at=now + timedelta(hours=1)))
        await db.commit()

    await transition_maintenance_schedules(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 1)
    assert server.status == ServerStatus.MAINTENANCE.value
    assert server.version == 1  # 이미 MAINTENANCE 면 다시 올리지 않는다


async def test_maintenance_job_writes_scheduler_log(factory):
    # 점검 전환 잡이 성공 실행되면 대시보드(F21)용 SchedulerLog(UC13) 한 행을 남긴다.
    # processed 는 이번 실행에서 실제로 상태가 바뀐 서버 수(여기선 진입 1건)와 같다.
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        _seed_admin(db)
        db.add(_server(1, status=ServerStatus.AVAILABLE))
        await db.flush()
        db.add(_schedule(1, start_at=now - timedelta(minutes=5),
                         end_at=now + timedelta(hours=1)))
        await db.commit()

    await transition_maintenance_schedules(session_factory=factory)

    async with factory() as db:
        logs = (
            await db.execute(select(SchedulerLog).where(SchedulerLog.uc_id == "UC13"))
        ).scalars().all()
    assert len(logs) == 1
    assert logs[0].success is True
    assert logs[0].processed_count == 1
