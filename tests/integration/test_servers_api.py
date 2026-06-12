"""서버 도메인 API 통합 테스트(UC23, Postgres·Redis 컨테이너 필요).

- GET /servers/{id}/health-trend: MGR/ADM 은 위험·추세·이력, STU 는 403
- 없는 서버는 404

위험·이력은 client 픽스처가 쓰는 것과 같은 Postgres 에 직접 적재한다
(라우터는 읽기 전용이라 잡 없이 데이터를 미리 넣어 조회만 검증한다).
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.models import Server, ServerHealthHistory

pytestmark = pytest.mark.integration


def _server(server_id: int, *, health_score: int, risk_score: float) -> Server:
    return Server(id=server_id, name=f"s{server_id}", ip=f"10.0.0.{server_id}",
                  cpu_cores=8, ram_gb=32, health_score=health_score, risk_score=risk_score)


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


async def _seed_declining_server(seed_session, server_id: int) -> None:
    """위험·하락 이력을 가진 서버 한 대를 적재한다."""
    now = datetime.now(tz=timezone.utc)
    async with seed_session() as db:
        db.add(_server(server_id, health_score=40, risk_score=82.0))
        await db.flush()  # 서버 먼저 적재(이력의 FK 대상)
        scores = [90, 82, 74, 66, 58, 50, 40]
        for day_offset, score in enumerate(reversed(scores)):
            db.add(ServerHealthHistory(server_id=server_id, score=score,
                                       recorded_at=now - timedelta(days=day_offset)))
        await db.commit()


async def test_health_trend_returns_fields_for_admin(client, seed_session):
    await _seed_declining_server(seed_session, 1)

    token = await _register_and_login(client, email="adm-ht@b.com", role="ADM")
    response = await client.get(
        "/servers/1/health-trend", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["serverId"] == 1
    assert body["healthScore"] == 40
    assert body["riskScore"] == 82.0
    assert body["trend"] == "DEGRADING"  # 하락 이력 → 열화
    assert len(body["history"]) == 7
    assert body["history"][0]["healthScore"] == 90  # 시간순 첫 점
    assert body["drivers"]  # 근거 문구가 비어 있지 않다


async def test_health_trend_allowed_for_manager(client, seed_session):
    await _seed_declining_server(seed_session, 2)

    token = await _register_and_login(client, email="mgr-ht@b.com", role="MGR")
    response = await client.get(
        "/servers/2/health-trend", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["serverId"] == 2


async def test_health_trend_forbidden_for_student(client, seed_session):
    await _seed_declining_server(seed_session, 3)

    token = await _register_and_login(client, email="stu-ht@b.com", role="STU")
    response = await client.get(
        "/servers/3/health-trend", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


async def test_health_trend_empty_history_returns_stable(client, seed_session):
    # 건강점수 이력이 전혀 없는 서버: history 는 비고, 기울기가 정의 안 돼 trend 는 STABLE,
    # 근거 신호도 없어 drivers 는 빈 목록이며 200 으로 응답한다.
    async with seed_session() as db:
        db.add(_server(4, health_score=100, risk_score=0.0))
        await db.commit()

    token = await _register_and_login(client, email="adm-ht-empty@b.com", role="ADM")
    response = await client.get(
        "/servers/4/health-trend", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["history"] == []
    assert body["trend"] == "STABLE"
    assert body["drivers"] == []


async def test_health_trend_missing_server_returns_404(client):
    token = await _register_and_login(client, email="adm-ht404@b.com", role="ADM")
    response = await client.get(
        "/servers/999999/health-trend", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
