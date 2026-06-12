"""POST /approval-requests 통합 테스트 [F09 / UC08].

헬퍼: STU 회원가입·로그인으로 토큰 취득, Server 행 직접 삽입.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

# ── 헬퍼 ──────────────────────────────────────────────────────────────


async def _register_login(client: AsyncClient, email: str, role: str = "STU") -> str:
    """회원가입 후 로그인하여 액세스 토큰을 반환한다."""
    await client.post(
        "/auth/register",
        json={"name": "테스터", "email": email, "password": "pass1234", "role": role, "teamId": 1},
    )
    login = await client.post("/auth/login", json={"email": email, "password": "pass1234"})
    return login.json()["accessToken"]


async def _insert_server(client: AsyncClient) -> int:
    """테스트용 서버를 DB에 직접 삽입하고 서버 id를 반환한다.

    conftest의 client 픽스처가 노출하는 override_get_db를 통해 세션을 얻을 수 없으므로
    ADM 계정으로 시드 API가 없는 현 구조에서는 app의 dependency_overrides에 달린
    세션 팩토리를 활용해 직접 INSERT 한다.
    """
    # app.dependency_overrides[get_db]가 등록된 세션 팩토리를 꺼내 쓴다.
    from app.core.deps import get_db
    from app.main import app
    from app.models.server import Server

    override = app.dependency_overrides.get(get_db)
    # override는 async generator factory다.
    gen = override()
    session: AsyncSession = await gen.__anext__()
    try:
        server = Server(name="gpu-01", ip="10.0.0.1", cpu_cores=8, ram_gb=32)
        session.add(server)
        await session.commit()
        await session.refresh(server)
        return server.id
    finally:
        try:
            await gen.aclose()
        except StopAsyncIteration:
            pass


# ── 정상 경로 ──────────────────────────────────────────────────────────


async def test_create_approval_request_returns_201(client: AsyncClient):
    """STU가 올바른 body를 보내면 201과 {approvalRequestId, status:"PENDING"}을 받는다."""
    token = await _register_login(client, "stu_happy@test.com")
    server_id = await _insert_server(client)

    resp = await client.post(
        "/approval-requests",
        json={
            "serverId": server_id,
            "startTime": "2026-07-01T09:00:00Z",
            "endTime": "2026-07-01T18:00:00Z",
            "reason": "논문 실험",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert "approvalRequestId" in body
    assert body["status"] == "PENDING"
    assert isinstance(body["approvalRequestId"], int)


async def test_create_approval_request_reason_optional(client: AsyncClient):
    """reason 필드는 선택 사항이다."""
    token = await _register_login(client, "stu_noreason@test.com")
    server_id = await _insert_server(client)

    resp = await client.post(
        "/approval-requests",
        json={
            "serverId": server_id,
            "startTime": "2026-07-02T09:00:00Z",
            "endTime": "2026-07-02T18:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "PENDING"


# ── 인증 오류 ──────────────────────────────────────────────────────────


async def test_create_approval_request_no_token_returns_401(client: AsyncClient):
    """토큰 없이 요청하면 401을 반환한다."""
    server_id = await _insert_server(client)

    resp = await client.post(
        "/approval-requests",
        json={
            "serverId": server_id,
            "startTime": "2026-07-03T09:00:00Z",
            "endTime": "2026-07-03T18:00:00Z",
        },
    )

    assert resp.status_code == 401


# ── 유효성 오류 (400) ──────────────────────────────────────────────────


async def test_create_approval_request_start_after_end_returns_400(client: AsyncClient):
    """startTime >= endTime 이면 400을 반환한다."""
    token = await _register_login(client, "stu_badtime@test.com")
    server_id = await _insert_server(client)

    resp = await client.post(
        "/approval-requests",
        json={
            "serverId": server_id,
            "startTime": "2026-07-04T18:00:00Z",
            "endTime": "2026-07-04T09:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400


async def test_create_approval_request_equal_times_returns_400(client: AsyncClient):
    """startTime == endTime 이면 400을 반환한다."""
    token = await _register_login(client, "stu_equaltime@test.com")
    server_id = await _insert_server(client)

    resp = await client.post(
        "/approval-requests",
        json={
            "serverId": server_id,
            "startTime": "2026-07-05T09:00:00Z",
            "endTime": "2026-07-05T09:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400


# ── 404 ────────────────────────────────────────────────────────────────


async def test_create_approval_request_unknown_server_returns_404(client: AsyncClient):
    """존재하지 않는 serverId면 404를 반환한다."""
    token = await _register_login(client, "stu_noserver@test.com")

    resp = await client.post(
        "/approval-requests",
        json={
            "serverId": 999999,
            "startTime": "2026-07-06T09:00:00Z",
            "endTime": "2026-07-06T18:00:00Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404


# ── 409 (중복) ─────────────────────────────────────────────────────────


async def test_create_approval_request_duplicate_pending_returns_409(client: AsyncClient):
    """같은 서버에 PENDING 요청이 이미 있으면 409를 반환한다."""
    token = await _register_login(client, "stu_dup@test.com")
    server_id = await _insert_server(client)

    payload = {
        "serverId": server_id,
        "startTime": "2026-07-07T09:00:00Z",
        "endTime": "2026-07-07T18:00:00Z",
    }

    first = await client.post(
        "/approval-requests",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201

    second = await client.post(
        "/approval-requests",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409
