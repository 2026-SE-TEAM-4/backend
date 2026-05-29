"""개발용 최소 시드 데이터.

스키마가 적용된 DB(`alembic upgrade head` 이후)에서 수동으로 실행한다.
실행: 컨테이너 안에서 `python -m scripts.seed`.
"""

import asyncio

from app.database import SessionLocal
from app.models import Server, Team, User
from app.models.enums import ServerStatus, UserRole


async def seed() -> None:
    async with SessionLocal() as session:
        team = Team(name="Lab-A", code="LAB-A", total_quota_limit=10)
        session.add(team)
        await session.flush()  # team.id 확보

        session.add_all(
            [
                User(name="홍길동", email="hong@example.com", role=UserRole.STU.value, team_id=team.id),
                User(name="김관리", email="kim@example.com", role=UserRole.MGR.value, team_id=team.id),
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
    print("시드 완료: 팀 1, 사용자 2, 서버 2")


if __name__ == "__main__":
    asyncio.run(seed())
