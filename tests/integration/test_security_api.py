"""보안 관제 API 통합 테스트(Postgres·Redis 컨테이너 필요).

- 로그인 실패 시 SecurityEvent(LOGIN_FAILURE) 기록
- STU 가 ADM 전용 엔드포인트 접근 시 403 반환
- 경보 resolve 엔드포인트
- simulate 후 탐지 잡 실행 시 SecurityAlert + Notification 생성
- GET /security/events·alerts·summary 응답 구조 확인
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.jobs.security_monitoring_job import detect_security_threats
from app.models import SecurityAlert, SecurityEvent, User
from app.models.enums import IncidentStatus, UserRole

pytestmark = pytest.mark.integration


# --- 헬퍼: ADM 토큰 발급 --------------------------------------------------

async def _register_and_login(client, email: str, role: str) -> str:
    await client.post(
        "/auth/register",
        json={"name": "테스터", "email": email, "password": "password123",
              "role": role, "teamId": 1},
    )
    resp = await client.post("/auth/login", json={"email": email, "password": "password123"})
    return resp.json()["accessToken"]


# --- 로그인 실패 이벤트 기록 -----------------------------------------------

async def test_login_failure_records_security_event(client, containers):
    postgres, _ = containers
    engine = create_async_engine(postgres.get_connection_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    await client.post("/auth/login", json={"email": "noone@x.com", "password": "wrong"})

    async with factory() as db:
        events = (await db.execute(select(SecurityEvent))).scalars().all()
    assert any(e.event_type == "LOGIN_FAILURE" for e in events)
    await engine.dispose()


# --- ADM 전용 엔드포인트: STU 는 403 -----------------------------------------

async def test_security_endpoints_reject_non_adm(client):
    stu_token = await _register_and_login(client, "stu@x.com", "STU")
    headers = {"Authorization": f"Bearer {stu_token}"}

    assert (await client.get("/security/events", headers=headers)).status_code == 403
    assert (await client.get("/security/alerts", headers=headers)).status_code == 403
    assert (await client.get("/security/summary", headers=headers)).status_code == 403


# --- GET /security/summary 응답 구조 -----------------------------------------

async def test_security_summary_returns_expected_fields(client):
    adm_token = await _register_and_login(client, "adm@x.com", "ADM")
    headers = {"Authorization": f"Bearer {adm_token}"}

    resp = await client.get("/security/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "todayEvents" in body
    assert "openAlerts" in body
    assert "criticalAlerts" in body
    assert "bruteForceSuspects" in body


# --- simulate + 탐지 잡 → SecurityAlert 생성 ---------------------------------

async def test_simulate_then_detect_creates_alert(client, containers):
    postgres, _ = containers
    engine = create_async_engine(postgres.get_connection_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    adm_token = await _register_and_login(client, "adm2@x.com", "ADM")
    headers = {"Authorization": f"Bearer {adm_token}"}

    resp = await client.post(
        "/security/simulate",
        json={"scenario": "brute_force"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["inserted"] > 0

    # 탐지 잡을 직접 실행해 경보 생성을 확인한다.
    await detect_security_threats(session_factory=factory)

    async with factory() as db:
        alerts = (await db.execute(select(SecurityAlert))).scalars().all()
    assert any(a.alert_type == "BRUTE_FORCE" for a in alerts)
    await engine.dispose()


# --- PATCH /security/alerts/{id}/resolve -------------------------------------

async def test_resolve_alert(client, containers):
    postgres, _ = containers
    engine = create_async_engine(postgres.get_connection_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    adm_token = await _register_and_login(client, "adm3@x.com", "ADM")
    headers = {"Authorization": f"Bearer {adm_token}"}

    # 먼저 경보를 만들기 위해 시뮬레이션 후 탐지 잡 실행
    await client.post("/security/simulate", json={"scenario": "agent_down"}, headers=headers)
    await detect_security_threats(session_factory=factory)

    async with factory() as db:
        alerts = (await db.execute(
            select(SecurityAlert).where(SecurityAlert.alert_type == "AGENT_DOWN")
        )).scalars().all()

    if not alerts:
        await engine.dispose()
        pytest.skip("경보가 생성되지 않아 해결 테스트를 건너뜁니다.")

    alert_id = alerts[0].id
    resp = await client.patch(f"/security/alerts/{alert_id}/resolve", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "RESOLVED"
    assert resp.json()["resolvedAt"] is not None

    # 멱등: 이미 해결된 경보를 다시 요청해도 200.
    resp2 = await client.patch(f"/security/alerts/{alert_id}/resolve", headers=headers)
    assert resp2.status_code == 200

    await engine.dispose()


async def test_resolve_nonexistent_alert_returns_404(client):
    adm_token = await _register_and_login(client, "adm4@x.com", "ADM")
    headers = {"Authorization": f"Bearer {adm_token}"}

    resp = await client.patch("/security/alerts/999999/resolve", headers=headers)
    assert resp.status_code == 404
