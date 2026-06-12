"""AIOps 기저 파이프라인 잡 통합 테스트(Postgres 컨테이너 필요).

- 메트릭 수집(P0): 응답 서버는 OK, 무응답 서버는 MISSING으로 적재
- 이상탐지(F27): μ±2σ 이탈 시 AnomalyRecord 기록 + 디바운스
- 건강점수(F28): health_score 산출 + 낙관적 락(version) 미변경 검증
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.config import settings
from app.database import Base
from app.jobs.anomaly_detection_job import detect_anomalies
from app.jobs.health_score_job import compute_health_scores
from app.jobs.metric_collection_job import collect_server_metrics
from app.models import AnomalyRecord, Server, ServerHealthHistory, ServerMetric

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


def _server(server_id: int) -> Server:
    return Server(id=server_id, name=f"s{server_id}", ip=f"10.0.0.{server_id}",
                  cpu_cores=8, ram_gb=32)


# --- P0: 메트릭 수집 -------------------------------------------------------

async def test_collect_writes_ok_for_responding_and_missing_for_down(factory):
    async with factory() as db:
        db.add_all([_server(1), _server(2)])
        await db.commit()

    base_port = settings.serverpool_base_port

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == base_port:  # 서버 1만 응답
            return httpx.Response(200, json={
                "cpuUsage": 50.0, "memUsage": 40.0, "netUsage": 5.0,
                "gpuUsage": None, "status": "OK"})
        raise httpx.ConnectError("agent down")  # 서버 2 무응답

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await collect_server_metrics(session_factory=factory, client=client)

    async with factory() as db:
        rows = (await db.execute(select(ServerMetric))).scalars().all()
        by_server = {r.server_id: r for r in rows}
    assert by_server[1].status == "OK"
    assert by_server[1].cpu_usage == 50.0
    assert by_server[1].gpu_usage is None
    assert by_server[2].status == "MISSING"


# --- F27: 이상탐지 ---------------------------------------------------------

async def _seed_cpu_series(db, server_id: int, *, latest_cpu: float) -> None:
    base = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    for i in range(60):  # 안정 구간(±1, σ>0)
        db.add(ServerMetric(server_id=server_id, cpu_usage=50.0 + (1 if i % 2 else -1),
               mem_usage=40.0, net_usage=5.0, gpu_usage=None, status="OK",
               collected_at=base + timedelta(minutes=i)))
    db.add(ServerMetric(server_id=server_id, cpu_usage=latest_cpu, mem_usage=40.0,
           net_usage=5.0, gpu_usage=None, status="OK",
           collected_at=base + timedelta(minutes=61)))


async def test_detects_cpu_outlier_only(factory):
    async with factory() as db:
        db.add(_server(1))
        await _seed_cpu_series(db, 1, latest_cpu=99.0)  # 명백한 이탈
        await db.commit()

    await detect_anomalies(session_factory=factory)

    async with factory() as db:
        records = (await db.execute(select(AnomalyRecord))).scalars().all()
    assert len(records) == 1
    assert records[0].metric == "CPU"
    assert records[0].current_value == 99.0


async def test_no_anomaly_for_stable_series(factory):
    async with factory() as db:
        db.add(_server(1))
        await _seed_cpu_series(db, 1, latest_cpu=50.5)  # 밴드 안
        await db.commit()

    await detect_anomalies(session_factory=factory)

    async with factory() as db:
        count = len((await db.execute(select(AnomalyRecord))).scalars().all())
    assert count == 0


async def test_anomaly_is_debounced_on_repeat_run(factory):
    async with factory() as db:
        db.add(_server(1))
        await _seed_cpu_series(db, 1, latest_cpu=99.0)
        await db.commit()

    await detect_anomalies(session_factory=factory)
    await detect_anomalies(session_factory=factory)  # 10분 내 중복 → 미기록

    async with factory() as db:
        count = len((await db.execute(select(AnomalyRecord))).scalars().all())
    assert count == 1


# --- F28: 건강점수 + 낙관적 락 미변경 --------------------------------------

async def test_health_score_set_without_bumping_version(factory):
    async with factory() as db:
        db.add(_server(1))
        db.add(ServerMetric(server_id=1, cpu_usage=100.0, mem_usage=100.0,
               net_usage=10.0, gpu_usage=None, status="OK"))
        await db.commit()

    await compute_health_scores(session_factory=factory)

    async with factory() as db:
        server = await db.get(Server, 1)
    assert server.health_score == 68  # 100 - (cpu 16 + mem 16)
    assert server.version == 1  # 건강점수 갱신이 낙관적 락을 건드리지 않는다


async def test_health_score_appends_history_row(factory):
    # 건강점수를 산출한 같은 실행에서 ServerHealthHistory 에 한 행이 남아야 한다(UC23 추세용).
    async with factory() as db:
        db.add(_server(1))
        db.add(ServerMetric(server_id=1, cpu_usage=100.0, mem_usage=100.0,
               net_usage=10.0, gpu_usage=None, status="OK"))
        await db.commit()

    await compute_health_scores(session_factory=factory)

    async with factory() as db:
        history = (await db.execute(select(ServerHealthHistory))).scalars().all()
        server = await db.get(Server, 1)
    assert len(history) == 1
    assert history[0].server_id == 1
    assert history[0].score == 68  # Server.health_score 와 같은 값을 이력에도 남긴다
    assert server.version == 1  # 이력 추가가 낙관적 락을 건드리지 않는다
