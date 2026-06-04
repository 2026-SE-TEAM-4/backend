"""회원가입(UC22)·로그인(UC23) 통합 테스트. Postgres·Redis 컨테이너가 필요하다."""

import pytest

pytestmark = pytest.mark.integration


async def test_register_login_me_happy_path(client):
    register = await client.post(
        "/auth/register",
        json={"name": "홍길동", "email": "a@b.com", "password": "password123",
              "role": "STU", "teamId": 1},
    )
    assert register.status_code == 201
    body = register.json()
    assert body["teamId"] == 1
    assert "password" not in body and "hashedPassword" not in body

    login = await client.post("/auth/login", json={"email": "a@b.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "STU"
    token = login.json()["accessToken"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@b.com"
    assert me.json()["lockedUntil"] is None


async def test_duplicate_email_returns_409(client):
    body = {"name": "x", "email": "dup@b.com", "password": "password123", "role": "STU", "teamId": 1}
    assert (await client.post("/auth/register", json=body)).status_code == 201
    assert (await client.post("/auth/register", json=body)).status_code == 409


async def test_register_unknown_team_returns_422(client):
    register = await client.post(
        "/auth/register",
        json={"name": "x", "email": "t@b.com", "password": "password123",
              "role": "STU", "teamId": 999},
    )
    assert register.status_code == 422


async def test_login_locks_account_after_threshold(client):
    await client.post(
        "/auth/register",
        json={"name": "x", "email": "lock@b.com", "password": "password123",
              "role": "STU", "teamId": 1},
    )
    last = None
    for _ in range(5):  # LOGIN_FAIL_MAX = 5
        last = await client.post("/auth/login", json={"email": "lock@b.com", "password": "wrong"})
    assert last.status_code == 429  # 임계 도달 시 잠금

    # 잠금 중에는 올바른 비밀번호로도 거부된다.
    retry = await client.post("/auth/login", json={"email": "lock@b.com", "password": "password123"})
    assert retry.status_code == 429


async def test_me_requires_valid_token(client):
    assert (await client.get("/auth/me")).status_code == 401
    bad = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert bad.status_code == 401
