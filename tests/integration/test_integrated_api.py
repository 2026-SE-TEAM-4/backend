"""통합 브랜치에서 새로 노출한 엔드포인트의 통합 테스트(Postgres·Redis 컨테이너 필요).

대상: 서버 CRUD(F01·F02·F08·F14·F15·F16), Quota 조정(F13), 알림 읽음(F18),
계정 잠금 해제(F20). 인증은 시스템 공통 JWT 를 쓴다(스텁 헤더 아님).
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  메타데이터 등록
from app.models import Notification, Quota, Server, User

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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- 서버 CRUD ---

async def test_admin_creates_and_lists_server(client):
    token = _auth(await _register_and_login(client, email="adm-cr@b.com", role="ADM"))
    created = await client.post(
        "/servers",
        headers=token,
        json={"name": "gpu-x", "ip": "10.1.0.1", "cpuCores": 16, "ramGb": 64,
              "gpuModel": "RTX4090", "group": "Lab-A GPU"},
    )
    assert created.status_code == 201
    server_id = created.json()["id"]

    listed = await client.get("/servers", headers=token)
    assert listed.status_code == 200
    names = [s["name"] for s in listed.json()["servers"]]
    assert "gpu-x" in names

    detail = await client.get(f"/servers/{server_id}", headers=token)
    assert detail.status_code == 200
    assert detail.json()["spec"]["cpuCores"] == 16


async def test_create_server_duplicate_ip_returns_409(client):
    token = _auth(await _register_and_login(client, email="adm-dup@b.com", role="ADM"))
    body = {"name": "dup-a", "ip": "10.1.0.9", "cpuCores": 8, "ramGb": 32}
    assert (await client.post("/servers", headers=token, json=body)).status_code == 201
    body2 = {"name": "dup-b", "ip": "10.1.0.9", "cpuCores": 8, "ramGb": 32}
    assert (await client.post("/servers", headers=token, json=body2)).status_code == 409


async def test_student_cannot_create_server(client):
    token = _auth(await _register_and_login(client, email="stu-cr@b.com", role="STU"))
    response = await client.post(
        "/servers", headers=token,
        json={"name": "nope", "ip": "10.1.0.50", "cpuCores": 8, "ramGb": 32},
    )
    assert response.status_code == 403


async def test_alternatives_returns_similar_available_servers(client, seed_session):
    async with seed_session() as db:
        db.add_all([
            Server(id=10, name="src", ip="10.2.0.1", cpu_cores=16, ram_gb=64,
                   gpu_model="RTX4090", status="RESERVED"),
            Server(id=11, name="alt", ip="10.2.0.2", cpu_cores=16, ram_gb=64,
                   gpu_model="RTX4090", status="AVAILABLE"),
        ])
        await db.commit()
    token = _auth(await _register_and_login(client, email="stu-alt@b.com", role="STU"))
    response = await client.get("/servers/alternatives?serverId=10", headers=token)
    assert response.status_code == 200
    ids = [a["id"] for a in response.json()["alternatives"]]
    assert 11 in ids


async def test_admin_soft_deletes_server(client):
    token = _auth(await _register_and_login(client, email="adm-del@b.com", role="ADM"))
    created = await client.post(
        "/servers", headers=token,
        json={"name": "to-del", "ip": "10.1.0.77", "cpuCores": 8, "ramGb": 32},
    )
    server_id = created.json()["id"]
    deleted = await client.delete(f"/servers/{server_id}", headers=token)
    assert deleted.status_code == 200
    assert (await client.get(f"/servers/{server_id}", headers=token)).status_code == 404


async def test_admin_creates_maintenance(client):
    token = _auth(await _register_and_login(client, email="adm-mnt@b.com", role="ADM"))
    created = await client.post(
        "/servers", headers=token,
        json={"name": "mnt-srv", "ip": "10.1.0.88", "cpuCores": 8, "ramGb": 32},
    )
    server_id = created.json()["id"]
    start = datetime.now(tz=timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=2)
    response = await client.post(
        f"/servers/{server_id}/maintenances", headers=token,
        json={"startAt": start.isoformat(), "endAt": end.isoformat(), "reason": "디스크 교체"},
    )
    assert response.status_code == 201
    assert response.json()["maintenanceId"] > 0


# --- Quota 조정(F13) ---

async def test_list_team_quotas_includes_name_and_version(client, seed_session):
    token = _auth(await _register_and_login(client, email="mgr-ql@b.com", role="MGR"))
    user_id = (await client.get("/auth/me", headers=token)).json()["id"]
    async with seed_session() as db:
        db.add(Quota(id=110, user_id=user_id, team_id=1, limit=4, used=2, version=3))
        await db.commit()
    res = await client.get("/teams/1/quotas", headers=token)
    assert res.status_code == 200
    row = next(q for q in res.json() if q["id"] == 110)
    assert row["version"] == 3
    assert isinstance(row["user_name"], str) and row["user_name"]


async def test_manager_updates_team_quota(client, seed_session):
    token = _auth(await _register_and_login(client, email="mgr-q@b.com", role="MGR"))
    me = await client.get("/auth/me", headers=token)
    user_id = me.json()["id"]
    async with seed_session() as db:
        db.add(Quota(id=100, user_id=user_id, team_id=1, limit=2, used=1, version=1))
        await db.commit()

    ok = await client.patch("/quotas/100", headers=token, json={"limit": 5, "version": 1})
    assert ok.status_code == 200
    assert ok.json()["limit"] == 5
    assert ok.json()["version"] == 2

    stale = await client.patch("/quotas/100", headers=token, json={"limit": 6, "version": 1})
    assert stale.status_code == 409  # version 불일치


async def test_quota_below_used_returns_400(client, seed_session):
    token = _auth(await _register_and_login(client, email="mgr-q2@b.com", role="MGR"))
    user_id = (await client.get("/auth/me", headers=token)).json()["id"]
    async with seed_session() as db:
        db.add(Quota(id=101, user_id=user_id, team_id=1, limit=3, used=3, version=1))
        await db.commit()
    response = await client.patch("/quotas/101", headers=token, json={"limit": 1, "version": 1})
    assert response.status_code == 400


# --- 알림 읽음(F18) ---

async def test_owner_marks_notification_read(client, seed_session):
    token = _auth(await _register_and_login(client, email="stu-n@b.com", role="STU"))
    user_id = (await client.get("/auth/me", headers=token)).json()["id"]
    async with seed_session() as db:
        db.add(Notification(id=200, user_id=user_id, type="APPROVAL", message="승인됨"))
        await db.commit()
    response = await client.patch("/notifications/200/read", headers=token)
    assert response.status_code == 200
    assert response.json()["read_at"] is not None


async def test_cannot_read_others_notification(client, seed_session):
    owner = _auth(await _register_and_login(client, email="owner-n@b.com", role="STU"))
    owner_id = (await client.get("/auth/me", headers=owner)).json()["id"]
    async with seed_session() as db:
        db.add(Notification(id=201, user_id=owner_id, type="APPROVAL", message="x"))
        await db.commit()
    other = _auth(await _register_and_login(client, email="other-n@b.com", role="STU"))
    response = await client.patch("/notifications/201/read", headers=other)
    assert response.status_code == 403


# --- 계정 잠금 해제(F20) ---

async def test_admin_unlocks_user(client, seed_session):
    token = _auth(await _register_and_login(client, email="adm-unlock@b.com", role="ADM"))
    locked_until = datetime.now(tz=timezone.utc) + timedelta(minutes=15)
    async with seed_session() as db:
        db.add(User(id=300, name="잠김", email="locked@b.com", role="STU",
                    team_id=1, locked_until=locked_until))
        await db.commit()
    response = await client.patch("/users/300/unlock", headers=token)
    assert response.status_code == 200
    assert response.json()["lockedUntil"] is None


async def test_student_cannot_unlock(client, seed_session):
    token = _auth(await _register_and_login(client, email="stu-unlock@b.com", role="STU"))
    async with seed_session() as db:
        db.add(User(id=301, name="잠김2", email="locked2@b.com", role="STU", team_id=1))
        await db.commit()
    response = await client.patch("/users/301/unlock", headers=token)
    assert response.status_code == 403
