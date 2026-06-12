"""점검 스케줄 자동 상태 전환 잡(F30/UC13).

1분 주기로 실행. 점검 일정(MaintenanceSchedule)의 시각에 맞춰 서버 상태만 전환한다:
- start_at <= now < end_at 인데 서버가 MAINTENANCE 가 아니면 → MAINTENANCE(version+1)
- end_at <= now 인데 서버가 MAINTENANCE 면                  → AVAILABLE(version+1)

점검 중 활성 예약 처리(force 등)는 점검 등록(F16) 쪽에서 다루므로 여기서는 상태
전환만 한다. version 을 올리는 이유는 reservation_jobs 와 같다: 예약 흐름의 낙관적
락과 상태 전이를 일관되게 맞추기 위함이다(건강점수류의 version-미변경과 다름).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import MaintenanceSchedule, Server
from app.models.enums import ServerStatus
from app.services.scheduler_log import add_scheduler_log

logger = logging.getLogger(__name__)


async def transition_maintenance_schedules(
    *, session_factory: async_sessionmaker = SessionLocal
) -> None:
    """도래한 점검 일정에 따라 서버 상태를 MAINTENANCE/AVAILABLE 로 전환한다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            entered = await _enter_maintenance(db, now)
            exited = await _exit_maintenance(db, now)
            # 대시보드(F21)용 실행 이력: 이번에 상태를 전환한 서버 수를 처리량으로 남긴다.
            add_scheduler_log(db, "UC13", entered + exited)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("점검 상태 전환 잡 실패")


async def _enter_maintenance(db: AsyncSession, now: datetime) -> int:
    """점검 구간(start_at <= now < end_at)에 든 서버를 MAINTENANCE 로 전환한다(전환 건수 반환)."""
    rows = await db.execute(
        select(MaintenanceSchedule.server_id).where(
            MaintenanceSchedule.start_at <= now,
            MaintenanceSchedule.end_at > now,
        )
    )
    transitioned = 0
    for server_id in set(rows.scalars().all()):
        # 이미 MAINTENANCE 면 건너뛴다(불필요한 version 증가·재전이를 막는다).
        result = await db.execute(
            update(Server)
            .where(Server.id == server_id, Server.status != ServerStatus.MAINTENANCE.value)
            .values(status=ServerStatus.MAINTENANCE.value, version=Server.version + 1)
        )
        if result.rowcount > 0:
            transitioned += 1
            logger.info("서버 %d → MAINTENANCE 전환", server_id)
    return transitioned


async def _exit_maintenance(db: AsyncSession, now: datetime) -> int:
    """점검 종료(end_at <= now)된 서버를 MAINTENANCE 에서 AVAILABLE 로 되돌린다(전환 건수 반환)."""
    rows = await db.execute(
        select(MaintenanceSchedule.server_id).where(MaintenanceSchedule.end_at <= now)
    )
    transitioned = 0
    for server_id in set(rows.scalars().all()):
        # MAINTENANCE 인 서버만 되돌린다. 점검과 무관하게 IN_USE 등인 서버는 건드리지 않는다.
        result = await db.execute(
            update(Server)
            .where(Server.id == server_id, Server.status == ServerStatus.MAINTENANCE.value)
            .values(status=ServerStatus.AVAILABLE.value, version=Server.version + 1)
        )
        if result.rowcount > 0:
            transitioned += 1
            logger.info("서버 %d → AVAILABLE 전환(점검 종료)", server_id)
    return transitioned
