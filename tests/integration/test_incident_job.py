"""인시던트 상관 잡 통합 테스트(UC24, Postgres 컨테이너 필요).

- 같은 그룹의 미할당 이상 → 인시던트 1건 생성, 이상에 incident_id 부여
- OPEN 인시던트와 서버를 공유하는 새 이상 → 신규 생성 없이 기존에 부착
- 최근 이상이 15분보다 오래된 OPEN 인시던트 → RESOLVED 자동 종료
- 인시던트 신규 생성 시 ADM 사용자에게 INCIDENT 알림 1건
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.database import Base
from app.jobs.incident_correlation_job import correlate_anomalies
from app.models import AnomalyRecord, Incident, Notification, Server, Team, User

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


def _server(server_id: int, group_name: str | None = None) -> Server:
    return Server(id=server_id, name=f"s{server_id}", ip=f"10.0.0.{server_id}",
                  cpu_cores=8, ram_gb=32, group_name=group_name)


def _anomaly(server_id: int, *, detected_at: datetime, current_value: float = 99.0) -> AnomalyRecord:
    # current_value·mean·stddev 로 편차 = |99-50|/10 ≈ 4.9σ 가 되게 둔다.
    return AnomalyRecord(server_id=server_id, metric="CPU", current_value=current_value,
                         mean=50.0, stddev=10.0, detected_at=detected_at)


async def test_groups_unassigned_anomalies_into_one_incident(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add_all([_server(1, group_name="lab"), _server(2, group_name="lab")])
        await db.flush()  # 서버 먼저 적재(이상의 FK 대상)
        db.add_all([
            _anomaly(1, detected_at=now - timedelta(minutes=2)),
            _anomaly(2, detected_at=now - timedelta(minutes=1)),
        ])
        await db.commit()

    await correlate_anomalies(session_factory=factory)

    async with factory() as db:
        incidents = (await db.execute(select(Incident))).scalars().all()
        anomalies = (await db.execute(select(AnomalyRecord))).scalars().all()
    assert len(incidents) == 1
    assert incidents[0].anomaly_count == 2
    assert sorted(incidents[0].server_ids) == [1, 2]
    assert all(a.incident_id == incidents[0].id for a in anomalies)


async def test_new_anomaly_attaches_to_open_incident_sharing_server(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(_server(1, group_name="lab"))
        await db.flush()
        db.add(_anomaly(1, detected_at=now - timedelta(minutes=3)))
        await db.commit()

    await correlate_anomalies(session_factory=factory)  # 인시던트 1건 생성

    async with factory() as db:
        db.add(_anomaly(1, detected_at=now - timedelta(minutes=1)))  # 같은 서버 새 이상
        await db.commit()

    await correlate_anomalies(session_factory=factory)  # 부착(신규 생성 금지)

    async with factory() as db:
        incidents = (await db.execute(select(Incident))).scalars().all()
    assert len(incidents) == 1
    assert incidents[0].anomaly_count == 2


async def test_stale_open_incident_is_auto_resolved(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(_server(1, group_name="lab"))
        # 최근 이상이 20분 전이라 윈도우(10분) 밖 → 부착 대상은 아니지만
        # 이미 OPEN 인시던트에 묶여 있어 자동 종료 대상이다.
        incident = Incident(severity="INFO", status="OPEN", anomaly_count=1, server_ids=[1])
        db.add(incident)
        await db.flush()  # 서버·인시던트 먼저 적재(이상의 FK 대상)
        stale_anomaly = _anomaly(1, detected_at=now - timedelta(minutes=20))
        stale_anomaly.incident_id = incident.id
        db.add(stale_anomaly)
        await db.commit()

    await correlate_anomalies(session_factory=factory)

    async with factory() as db:
        incident = (await db.execute(select(Incident))).scalars().one()
    assert incident.status == "RESOLVED"
    assert incident.resolved_at is not None


async def test_new_incident_notifies_each_adm_once(factory):
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Team(id=1, name="Lab", code="LAB", total_quota_limit=10))
        db.add_all([
            User(id=1, name="adm", email="adm@b.com", role="ADM", team_id=1),
            User(id=2, name="stu", email="stu@b.com", role="STU", team_id=1),
        ])
        db.add(_server(1, group_name="lab"))
        await db.flush()
        db.add(_anomaly(1, detected_at=now - timedelta(minutes=1)))
        await db.commit()

    await correlate_anomalies(session_factory=factory)

    async with factory() as db:
        notifications = (await db.execute(select(Notification))).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].user_id == 1
    assert notifications[0].type == "INCIDENT"
