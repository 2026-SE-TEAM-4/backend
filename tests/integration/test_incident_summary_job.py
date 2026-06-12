"""LLM 원인 요약 잡 통합 테스트(UC25, Postgres 컨테이너 필요).

실제 Anthropic API 는 절대 호출하지 않는다. stub 비동기 클라이언트를 주입해
정해진 JSON 을 돌려주게 하고, 잡이 그것을 파싱해 IncidentSummary 로 저장하는지 본다.

- OPEN 인시던트 + 이상 + 메트릭 시드 → stub 주입 → IncidentSummary 1건 저장
- 같은 인시던트에 다시 돌려도 두 번째 요약은 생기지 않는다(인시던트당 1회, 캐시)
- api_key 가 비어 있으면 요약 없이 조용히 건너뛴다(크래시 없음)
"""

import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.jobs.incident_summary_job as incident_summary_job
import app.models  # noqa: F401  메타데이터 등록
from app.config import settings
from app.database import Base
from app.jobs.incident_summary_job import summarize_pending_incidents
from app.models import AnomalyRecord, Incident, IncidentSummary, Server, ServerMetric

pytestmark = pytest.mark.integration


# stub 응답을 흉내 내는 가벼운 객체들. 실제 Anthropic SDK 와 같은 모양만 갖춘다
# (response.content 는 .text 를 가진 블록 리스트).
class _StubBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubMessage:
    def __init__(self, text: str) -> None:
        self.content = [_StubBlock(text)]


class _StubMessages:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = 0

    async def create(self, **kwargs) -> _StubMessage:
        # 네트워크 없이 정해진 JSON 을 돌려준다. 호출 횟수를 세어 캐시(1회 호출)를 검증한다.
        self.calls += 1
        return _StubMessage(json.dumps(self._payload))


class _StubClient:
    """Anthropic 비동기 클라이언트 자리에 주입하는 stub. client.messages.create 만 흉내."""

    def __init__(self, payload: dict) -> None:
        self.messages = _StubMessages(payload)


_VALID_PAYLOAD = {
    "situation": "서버 1의 CPU 사용률이 평균을 크게 초과했습니다 (서버 1 CPU 99%).",
    "rootCauses": [
        {"cause": "CPU 과부하", "evidence": "서버 1 CPU 99% (평균 50%, stddev 10)"},
    ],
    "recommendations": [
        {"action": "부하 분산", "rationale": "단일 서버 포화 완화"},
    ],
}


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


async def _seed_open_incident(factory) -> int:
    """OPEN 인시던트 + 묶인 이상 + 서버 + 메트릭을 적재하고 인시던트 id 를 돌려준다."""
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add(Server(id=1, name="s1", ip="10.0.0.1", cpu_cores=8, ram_gb=32))
        incident = Incident(severity="WARNING", status="OPEN",
                            anomaly_count=1, server_ids=[1])
        db.add(incident)
        await db.flush()  # 서버·인시던트 먼저 적재(FK 대상)
        db.add(AnomalyRecord(server_id=1, metric="CPU", current_value=99.0,
                             mean=50.0, stddev=10.0, incident_id=incident.id))
        db.add(ServerMetric(server_id=1, cpu_usage=99.0, mem_usage=30.0,
                            net_usage=10.0, status="OK", collected_at=now))
        await db.commit()
        return incident.id


async def test_summarizes_open_incident_and_stores_one_row(factory, monkeypatch):
    # 키가 있는 것처럼 두고 stub 클라이언트를 주입한다(실제 네트워크 없음).
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    incident_id = await _seed_open_incident(factory)
    stub = _StubClient(_VALID_PAYLOAD)

    await summarize_pending_incidents(session_factory=factory, client=stub)

    async with factory() as db:
        summaries = (
            await db.execute(
                select(IncidentSummary).where(IncidentSummary.incident_id == incident_id)
            )
        ).scalars().all()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.situation.startswith("서버 1")
    assert summary.root_causes[0]["cause"] == "CPU 과부하"
    assert summary.recommendations[0]["action"] == "부하 분산"
    assert summary.model == settings.anthropic_model
    # 인시던트 1건 → 호출도 1회여야 한다(비용 절감).
    assert stub.messages.calls == 1


async def test_does_not_regenerate_when_summary_exists(factory, monkeypatch):
    # 이미 요약이 있으면 다시 만들지 않는다(인시던트당 1회 보장 → 추가 호출 없음).
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    await _seed_open_incident(factory)

    first = _StubClient(_VALID_PAYLOAD)
    await summarize_pending_incidents(session_factory=factory, client=first)
    second = _StubClient(_VALID_PAYLOAD)
    await summarize_pending_incidents(session_factory=factory, client=second)

    async with factory() as db:
        summaries = (
            await db.execute(select(IncidentSummary))
        ).scalars().all()

    # 요약은 여전히 1건이고, 두 번째 실행은 LLM 을 호출하지 않았다.
    assert len(summaries) == 1
    assert second.messages.calls == 0


async def test_skips_gracefully_when_api_key_missing(factory, monkeypatch):
    # 키가 비어 있으면 요약을 만들지 않고 조용히 건너뛴다(크래시 없음).
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    await _seed_open_incident(factory)
    stub = _StubClient(_VALID_PAYLOAD)

    await summarize_pending_incidents(session_factory=factory, client=stub)

    async with factory() as db:
        summaries = (await db.execute(select(IncidentSummary))).scalars().all()

    assert summaries == []
    assert stub.messages.calls == 0


async def test_one_failing_incident_does_not_block_others(factory, monkeypatch):
    # 한 인시던트의 응답 파싱이 깨져도 다른 인시던트 요약은 저장되어야 한다(잡 격리).
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    now = datetime.now(tz=timezone.utc)
    async with factory() as db:
        db.add_all([
            Server(id=1, name="s1", ip="10.0.0.1", cpu_cores=8, ram_gb=32),
            Server(id=2, name="s2", ip="10.0.0.2", cpu_cores=8, ram_gb=32),
        ])
        good = Incident(severity="INFO", status="OPEN", anomaly_count=1, server_ids=[1])
        bad = Incident(severity="INFO", status="OPEN", anomaly_count=1, server_ids=[2])
        db.add_all([good, bad])
        await db.flush()
        db.add_all([
            AnomalyRecord(server_id=1, metric="CPU", current_value=99.0,
                          mean=50.0, stddev=10.0, incident_id=good.id),
            AnomalyRecord(server_id=2, metric="MEM", current_value=95.0,
                          mean=40.0, stddev=5.0, incident_id=bad.id),
        ])
        await db.commit()
        good_id, bad_id = good.id, bad.id

    # 서버 2가 묶인 인시던트(bad)에는 깨진 JSON 을, 나머지에는 정상 JSON 을 돌려준다.
    class _MixedMessages(_StubMessages):
        async def create(self, **kwargs):
            self.calls += 1
            prompt = kwargs["messages"][0]["content"]
            if '"id": 2' in prompt or '"serverIds": [\n    2' in prompt or '"serverId": 2' in prompt:
                return _StubMessage("깨진 응답: JSON 아님")
            return _StubMessage(json.dumps(_VALID_PAYLOAD))

    class _MixedClient:
        def __init__(self) -> None:
            self.messages = _MixedMessages(_VALID_PAYLOAD)

    await summarize_pending_incidents(session_factory=factory, client=_MixedClient())

    async with factory() as db:
        good_rows = (
            await db.execute(
                select(IncidentSummary).where(IncidentSummary.incident_id == good_id)
            )
        ).scalars().all()
        bad_rows = (
            await db.execute(
                select(IncidentSummary).where(IncidentSummary.incident_id == bad_id)
            )
        ).scalars().all()

    # 정상 인시던트는 저장되고, 파싱 실패 인시던트는 저장되지 않는다.
    assert len(good_rows) == 1
    assert bad_rows == []
