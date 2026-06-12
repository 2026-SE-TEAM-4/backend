"""운영(ops) API 통합 테스트(UC24, Postgres·Redis 컨테이너 필요).

- GET /ops/incidents: MGR/ADM 은 인시던트 목록 + 노이즈 감소율, STU 는 403
- GET /ops/incidents/{id}: 묶인 이상 목록 반환, 없으면 404

인시던트·이상은 client 픽스처가 쓰는 것과 같은 Postgres 에 직접 적재한다
(라우터는 읽기 전용이라 잡 없이 데이터를 미리 넣어 조회만 검증한다).
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.models import AnomalyRecord, Forecast, Incident, IncidentSummary, Server


def _server(server_id: int) -> Server:
    return Server(id=server_id, name=f"s{server_id}", ip=f"10.0.0.{server_id}",
                  cpu_cores=8, ram_gb=32)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seed_session(containers):
    """client 픽스처와 같은 Postgres 를 가리키는 세션 팩토리(직접 적재용)."""
    postgres, _ = containers
    engine = create_async_engine(postgres.get_connection_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


async def _register_and_login(client, *, email: str, role: str) -> str:
    await client.post(
        "/auth/register",
        json={"name": role, "email": email, "password": "password123",
              "role": role, "teamId": 1},
    )
    login = await client.post("/auth/login", json={"email": email, "password": "password123"})
    return login.json()["accessToken"]


async def test_list_incidents_returns_incidents_and_rate_for_admin(client, seed_session):
    async with seed_session() as db:
        db.add_all([_server(1), _server(2)])
        incident = Incident(severity="WARNING", status="OPEN", anomaly_count=2, server_ids=[1, 2])
        db.add(incident)
        await db.flush()  # 서버·인시던트 먼저 적재(이상의 FK 대상)
        db.add_all([
            AnomalyRecord(server_id=1, metric="CPU", current_value=99.0, mean=50.0,
                          stddev=10.0, incident_id=incident.id),
            AnomalyRecord(server_id=2, metric="CPU", current_value=95.0, mean=50.0,
                          stddev=10.0, incident_id=incident.id),
        ])
        await db.commit()

    token = await _register_and_login(client, email="adm@b.com", role="ADM")
    response = await client.get("/ops/incidents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["incidents"]) == 1
    assert body["incidents"][0]["anomalyCount"] == 2
    assert body["incidents"][0]["serverIds"] == [1, 2]
    # 이상 2건이 인시던트 1건으로 묶임 → 1 - 1/2 = 0.5
    assert body["noiseReductionRate"] == 0.5


async def test_list_incidents_forbidden_for_student(client):
    token = await _register_and_login(client, email="stu@b.com", role="STU")
    response = await client.get("/ops/incidents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


async def test_noise_reduction_rate_is_zero_when_no_anomalies(client):
    # 이상이 하나도 없으면 0 으로 나눌 수 없으므로 감소율은 0.0 이다(0 나눗셈 가드).
    token = await _register_and_login(client, email="adm0@b.com", role="ADM")
    response = await client.get("/ops/incidents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["incidents"] == []
    assert body["noiseReductionRate"] == 0.0


async def test_get_incident_returns_linked_anomalies(client, seed_session):
    async with seed_session() as db:
        db.add(_server(1))
        incident = Incident(severity="INFO", status="OPEN", anomaly_count=1, server_ids=[1])
        db.add(incident)
        await db.flush()  # 서버·인시던트 먼저 적재(이상의 FK 대상)
        db.add(AnomalyRecord(server_id=1, metric="MEM", current_value=90.0, mean=40.0,
                             stddev=5.0, incident_id=incident.id))
        await db.commit()
        incident_id = incident.id

    token = await _register_and_login(client, email="mgr@b.com", role="MGR")
    response = await client.get(
        f"/ops/incidents/{incident_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["incident"]["id"] == incident_id
    assert len(body["anomalies"]) == 1
    assert body["anomalies"][0]["metric"] == "MEM"
    assert body["anomalies"][0]["serverId"] == 1


async def test_get_incident_missing_returns_404(client):
    token = await _register_and_login(client, email="adm2@b.com", role="ADM")
    response = await client.get(
        "/ops/incidents/999999", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def _forecast(
    server_id: int | None,
    metric: str,
    *,
    confidence: float = 0.8,
    generated_at: datetime | None = None,
) -> Forecast:
    forecast = Forecast(
        server_id=server_id,
        metric=metric,
        horizon=[{"ts": "2026-06-13T00:00:00+00:00", "yhat": 80.0,
                  "lower": 70.0, "upper": 90.0}],
        saturation_at=None,
        confidence=confidence,
    )
    if generated_at is not None:
        forecast.generated_at = generated_at
    return forecast


async def test_get_forecast_returns_stored_forecast_for_admin(client, seed_session):
    async with seed_session() as db:
        db.add(_server(1))
        await db.flush()  # 서버 먼저 적재(예측의 FK 대상)
        db.add(_forecast(1, "CPU"))
        await db.commit()

    token = await _register_and_login(client, email="adm-fc@b.com", role="ADM")
    response = await client.get(
        "/ops/forecast?serverId=1&metric=CPU", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["serverId"] == 1
    assert body["metric"] == "CPU"
    assert body["confidence"] == 0.8
    assert len(body["horizon"]) == 1


async def test_get_forecast_returns_most_recent_row(client, seed_session):
    # 같은 서버·메트릭에 예측이 여러 건이면 generated_at 이 가장 최근인 것을 돌려준다.
    now = datetime.now(tz=timezone.utc)
    async with seed_session() as db:
        db.add(_server(7))
        await db.flush()  # 서버 먼저 적재(예측의 FK 대상)
        db.add(_forecast(7, "CPU", confidence=0.3,
                         generated_at=now - timedelta(hours=2)))
        db.add(_forecast(7, "CPU", confidence=0.9, generated_at=now))
        await db.commit()

    token = await _register_and_login(client, email="adm-recent@b.com", role="ADM")
    response = await client.get(
        "/ops/forecast?serverId=7&metric=CPU", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    # 최신 행(confidence=0.9)이 반환되어야 한다(order_by generated_at desc limit 1).
    assert response.json()["confidence"] == 0.9


async def test_get_forecast_missing_returns_404(client):
    token = await _register_and_login(client, email="mgr-fc@b.com", role="MGR")
    response = await client.get(
        "/ops/forecast?serverId=999&metric=CPU", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


async def test_get_forecast_forbidden_for_student(client):
    token = await _register_and_login(client, email="stu-fc@b.com", role="STU")
    response = await client.get(
        "/ops/forecast?serverId=1&metric=CPU", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


async def _seed_incident_with_summary(seed_session) -> int:
    """인시던트 1건과 그 요약을 적재하고 인시던트 id 를 돌려준다."""
    async with seed_session() as db:
        incident = Incident(severity="WARNING", status="OPEN", anomaly_count=1, server_ids=[1])
        db.add(incident)
        await db.flush()  # 인시던트 먼저 적재(요약의 FK 대상)
        db.add(IncidentSummary(
            incident_id=incident.id,
            situation="서버 1 CPU 과부하",
            root_causes=[{"cause": "CPU 과부하", "evidence": "서버 1 CPU 99%"}],
            recommendations=[{"action": "부하 분산", "rationale": "단일 서버 포화 완화"}],
            model="claude-haiku-4-5-20251001",
        ))
        await db.commit()
        return incident.id


async def test_get_incident_summary_returns_stored_summary_for_admin(client, seed_session):
    incident_id = await _seed_incident_with_summary(seed_session)

    token = await _register_and_login(client, email="adm-sum@b.com", role="ADM")
    response = await client.get(
        f"/ops/incidents/{incident_id}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["incidentId"] == incident_id
    assert body["situation"] == "서버 1 CPU 과부하"
    assert body["rootCauses"][0]["cause"] == "CPU 과부하"
    assert body["recommendations"][0]["action"] == "부하 분산"
    assert body["model"] == "claude-haiku-4-5-20251001"


async def test_get_incident_summary_missing_returns_404(client):
    # 요약이 아직 생성되지 않은 인시던트(또는 없는 인시던트)는 404.
    token = await _register_and_login(client, email="mgr-sum@b.com", role="MGR")
    response = await client.get(
        "/ops/incidents/999999/summary", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


async def test_get_incident_summary_forbidden_for_student(client):
    token = await _register_and_login(client, email="stu-sum@b.com", role="STU")
    response = await client.get(
        "/ops/incidents/1/summary", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
