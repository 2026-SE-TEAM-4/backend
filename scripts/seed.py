"""개발용 최소 시드 데이터.

마이그레이션 직후 api 컨테이너 기동 시 자동 실행된다(docker-compose.yml command).
이미 데이터가 있으면 조용히 건너뛰므로 컨테이너를 재시작해도 중복 삽입되지 않는다.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.database import SessionLocal
from app.models import Server, Team, User
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    SecurityAlertType,
    SecurityEventType,
    ServerStatus,
    UserRole,
)
from app.models.security_alert import SecurityAlert
from app.models.security_event import SecurityEvent

_SEED_PASSWORD = "password123"


async def seed() -> None:
    async with SessionLocal() as session:
        already_seeded = (await session.execute(select(Team).limit(1))).scalar_one_or_none()
        if already_seeded:
            print("시드 건너뜀: 이미 데이터 존재")
            return

        team = Team(name="Lab-A", code="LAB-A", total_quota_limit=10)
        session.add(team)
        await session.flush()

        hashed = hash_password(_SEED_PASSWORD)
        session.add_all(
            [
                User(name="홍길동", email="hong@example.com", role=UserRole.STU.value,
                     team_id=team.id, hashed_password=hashed),
                User(name="김관리", email="kim@example.com", role=UserRole.MGR.value,
                     team_id=team.id, hashed_password=hashed),
                User(name="관리자", email="admin@example.com", role=UserRole.ADM.value,
                     team_id=team.id, hashed_password=hashed),
            ]
        )

        # 서버 풀 에이전트(agent-1~6)와 1:1 대응한다.
        # 사양은 server-pool/agent/config.py의 SERVER_SPECS와 일치해야 한다.
        session.add_all(
            [
                # --- HPC GPU 클러스터 ---
                Server(
                    name="gpu-a100-01", ip="10.0.0.1",
                    cpu_cores=64, ram_gb=256,
                    gpu_model="NVIDIA A100 80GB × 2",
                    group_name="HPC GPU 클러스터",
                    status=ServerStatus.AVAILABLE.value, version=1,
                ),
                # --- GPU 워크스테이션 ---
                Server(
                    name="gpu-rtx4090-01", ip="10.0.0.2",
                    cpu_cores=38, ram_gb=128,
                    gpu_model="NVIDIA RTX 4090 24GB × 4",
                    group_name="GPU 워크스테이션",
                    status=ServerStatus.AVAILABLE.value, version=1,
                ),
                Server(
                    name="gpu-rtx3090-01", ip="10.0.0.3",
                    cpu_cores=32, ram_gb=128,
                    gpu_model="NVIDIA RTX 3090 24GB × 2",
                    group_name="GPU 워크스테이션",
                    status=ServerStatus.AVAILABLE.value, version=1,
                ),
                # --- 추론 서버 ---
                Server(
                    name="gpu-t4-01", ip="10.0.0.4",
                    cpu_cores=16, ram_gb=64,
                    gpu_model="NVIDIA Tesla T4 16GB",
                    group_name="추론 서버",
                    status=ServerStatus.AVAILABLE.value, version=1,
                ),
                # --- CPU HPC 클러스터 ---
                Server(
                    name="cpu-xeon-01", ip="10.0.0.5",
                    cpu_cores=112, ram_gb=512,
                    gpu_model=None,
                    group_name="CPU HPC 클러스터",
                    status=ServerStatus.AVAILABLE.value, version=1,
                ),
                Server(
                    name="cpu-epyc-01", ip="10.0.0.6",
                    cpu_cores=96, ram_gb=384,
                    gpu_model=None,
                    group_name="CPU HPC 클러스터",
                    status=ServerStatus.AVAILABLE.value, version=1,
                ),
            ]
        )
        await session.commit()

        # 보안 관제 화면이 시드 직후 비어 보이지 않도록 샘플 이벤트·경보를 추가한다.
        now = datetime.now(tz=timezone.utc)
        session.add_all([
            SecurityEvent(
                event_type=SecurityEventType.LOGIN_FAILURE.value,
                severity=IncidentSeverity.INFO.value,
                source_ip="203.0.113.42",
                identifier="unknown@example.com",
                occurred_at=now - timedelta(hours=2),
            ),
            SecurityEvent(
                event_type=SecurityEventType.ACCESS_DENIED.value,
                severity=IncidentSeverity.WARNING.value,
                actor_id=1,
                source_ip="10.0.0.1",
                detail={"path": "/admin/reset/all"},
                occurred_at=now - timedelta(hours=1),
            ),
            SecurityEvent(
                event_type=SecurityEventType.ADMIN_ACTION.value,
                severity=IncidentSeverity.WARNING.value,
                actor_id=1,
                target_type="system",
                detail={"action": "reset_aiops"},
                occurred_at=now - timedelta(minutes=30),
            ),
        ])
        # 해결된 경보 예시 — 화면에 이력이 보이도록 한다.
        session.add(SecurityAlert(
            alert_type=SecurityAlertType.BRUTE_FORCE.value,
            severity=IncidentSeverity.WARNING.value,
            status=IncidentStatus.RESOLVED.value,
            subject="203.0.113.42",
            event_count=7,
            message="브루트포스 의심: 203.0.113.42 에서 7회 로그인 실패",
            started_at=now - timedelta(hours=3),
            resolved_at=now - timedelta(hours=2),
        ))
        await session.commit()

    print("시드 완료: 팀 1, 사용자 3(비밀번호 password123), 서버 6, 보안 이벤트 3건, 경보 1건")


if __name__ == "__main__":
    asyncio.run(seed())
