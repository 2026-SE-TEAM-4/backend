"""개발용 최소 시드 데이터.

스키마가 적용된 DB(`alembic upgrade head` 이후)에서 수동으로 실행한다.
실행: 컨테이너 안에서 `python -m scripts.seed`.
시드 사용자에게는 개발 로그인이 가능하도록 비밀번호 해시를 부여한다.
"""

import asyncio

from app.core.security import hash_password
from app.database import SessionLocal
from app.models import Server, Team, User
from app.models.enums import ServerStatus, UserRole

# 개발용 공통 비밀번호. 운영 데이터가 아니라 시연·테스트 편의를 위한 값이다.
_SEED_PASSWORD = "password123"


async def seed() -> None:
    async with SessionLocal() as session:
        team = Team(name="Lab-A", code="LAB-A", total_quota_limit=10)
        session.add(team)
        await session.flush()  # team.id 확보

        hashed = hash_password(_SEED_PASSWORD)
        session.add_all(
            [
                User(name="홍길동", email="hong@example.com", role=UserRole.STU.value,
                     team_id=team.id, hashed_password=hashed),
                User(name="김관리", email="kim@example.com", role=UserRole.MGR.value,
                     team_id=team.id, hashed_password=hashed),
            ]
        )
        session.add_all(
            [
                Server(name="gpu-01", ip="10.0.0.1", cpu_cores=16, ram_gb=64,
                       gpu_model="RTX4090", group_name="Lab-A GPU",
                       status=ServerStatus.AVAILABLE.value, version=1),
                Server(name="gpu-02", ip="10.0.0.2", cpu_cores=16, ram_gb=64,
                       gpu_model="RTX4090", group_name="Lab-A GPU",
                       status=ServerStatus.AVAILABLE.value, version=1),
            ]
        )
        await session.commit()
    print("시드 완료: 팀 1, 사용자 2(비밀번호 password123), 서버 2")


if __name__ == "__main__":
    asyncio.run(seed())
