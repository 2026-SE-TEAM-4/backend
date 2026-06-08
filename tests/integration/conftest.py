"""통합 테스트 픽스처: 실제 Postgres·Redis 컨테이너를 띄우고 앱에 연결한다.

DB 세션은 의존성 오버라이드로, Redis는 모듈 클라이언트 교체로 테스트 컨테이너를
바라보게 한다. 테스트마다 스키마를 새로 만들고 Redis를 비워 격리한다.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

import app.core.redis as redis_module
import app.models  # noqa: F401  모든 테이블을 Base.metadata에 등록
from app.core.deps import get_db
from app.database import Base
from app.main import app
from app.models import Team


@pytest.fixture(scope="session")
def containers():
    with (
        PostgresContainer("postgres:16", driver="asyncpg") as postgres,
        RedisContainer("redis:7") as redis,
    ):
        yield postgres, redis


@pytest_asyncio.fixture
async def client(containers):
    postgres, redis = containers
    engine = create_async_engine(postgres.get_connection_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(Team(name="Lab-A", code="LAB-A", total_quota_limit=10))
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    host = redis.get_container_host_ip()
    port = redis.get_exposed_port(6379)
    redis_module._client = Redis.from_url(f"redis://{host}:{port}/0", decode_responses=True)
    await redis_module._client.flushall()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    app.dependency_overrides.clear()
    await redis_module._client.aclose()
    redis_module._client = None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
