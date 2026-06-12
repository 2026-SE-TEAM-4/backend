"""예약 만료 자동 처리 스케줄러 잡 [UC16].

1분 주기로 실행. 두 가지 전이를 처리한다:
- RESERVED + start_time 도래 + end_time 미도래 → IN_USE  (서버: RESERVED → IN_USE)
- RESERVED/IN_USE + end_time 경과            → EXPIRED (서버: → AVAILABLE, Quota.used 감소)
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import Quota, Reservation, Server
from app.models.enums import ReservationStatus, ServerStatus
from app.services.scheduler_log import add_scheduler_log

logger = logging.getLogger(__name__)


async def process_reservation_transitions() -> None:
    """만료·사용 시작 대상 예약을 일괄 전이한다."""
    async with SessionLocal() as db:
        try:
            started = await _start_in_use(db)
            expired = await _expire_reservations(db)
            # 대시보드(F21)용 실행 이력: 이번에 전이한 예약 수를 처리량으로 남긴다.
            add_scheduler_log(db, "UC16", started + expired)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("예약 자동 전이 잡 실패")


async def _start_in_use(db) -> int:
    """start_time이 도래한 RESERVED 예약을 IN_USE로 전환한다(전이 건수 반환)."""
    now = datetime.now(tz=timezone.utc)

    rows = await db.execute(
        select(Reservation).where(
            Reservation.status == ReservationStatus.RESERVED.value,
            Reservation.start_time <= now,
            Reservation.end_time > now,
        )
    )
    reservations = rows.scalars().all()

    for reservation in reservations:
        reservation.status = ReservationStatus.IN_USE.value
        await db.execute(
            update(Server)
            .where(Server.id == reservation.server_id)
            .values(status=ServerStatus.IN_USE, version=Server.version + 1)
        )
        logger.info("예약 %d → IN_USE 전환 (서버 %d)", reservation.id, reservation.server_id)

    return len(reservations)


async def _expire_reservations(db) -> int:
    """end_time이 경과한 RESERVED/IN_USE 예약을 EXPIRED로 전환하고 서버를 반환한다(전이 건수 반환)."""
    now = datetime.now(tz=timezone.utc)

    rows = await db.execute(
        select(Reservation).where(
            Reservation.status.in_([
                ReservationStatus.RESERVED.value,
                ReservationStatus.IN_USE.value,
            ]),
            Reservation.end_time <= now,
        )
    )
    reservations = rows.scalars().all()

    for reservation in reservations:
        reservation.status = ReservationStatus.EXPIRED.value

        await db.execute(
            update(Server)
            .where(Server.id == reservation.server_id)
            .values(status=ServerStatus.AVAILABLE, version=Server.version + 1)
        )

        quota = await db.scalar(
            select(Quota).where(Quota.user_id == reservation.user_id)
        )
        if quota is not None and quota.used > 0:
            quota.used -= 1

        logger.info("예약 %d → EXPIRED (서버 %d 반환)", reservation.id, reservation.server_id)

    return len(reservations)
