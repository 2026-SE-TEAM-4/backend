"""유휴 서버 감지·자동 회수 잡(F24/UC15).

1분 주기로 실행. 점유(IN_USE) 중이지만 사용률이 낮은 서버를 경고 후 자동 회수한다.
스키마에 "회수 예정 시각" 필드가 없으므로 2단계를 알림으로 구현한다:

1. 최근 30분 평균 CPU 사용률이 유휴 임계 미만이고 최근 IDLE_WARNING 알림이 없으면
   → 점유자에게 IDLE_WARNING 알림 1건 발송(잠시 후 회수 예고). 이번엔 회수하지 않는다.
2. 유휴가 지속되고 IDLE_WARNING 이 유예 시간(15분)보다 오래됐으면 → 회수한다:
   Reservation=RECLAIMED, Server=AVAILABLE(version+1), Quota.used 감소, RECLAIM 알림.

상태 전이라 reservation_jobs 와 같은 트랜잭션·version 증가 패턴을 그대로 따른다.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import Notification, Quota, Reservation, Server, ServerMetric
from app.models.enums import MetricStatus, ReservationStatus, ServerStatus
from app.services.idle_reclaim import (
    IDLE_LOOKBACK,
    RECLAIM_GRACE,
    is_idle,
)
from app.services.scheduler_log import add_scheduler_log

logger = logging.getLogger(__name__)

# payload 에 서버를 식별해 두어 같은 서버의 경고만 골라보기 위한 알림 타입.
_WARNING_TYPE = "IDLE_WARNING"
_RECLAIM_TYPE = "RECLAIM"


async def reclaim_idle_servers(*, session_factory: async_sessionmaker = SessionLocal) -> None:
    """유휴 점유 서버를 경고 후 자동 회수한다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            reservations = await _active_in_use_reservations(db)
            reclaimed = 0
            for reservation in reservations:
                reclaimed += await _handle_reservation(db, reservation, now)
            # 대시보드(F21)용 실행 이력: 이번에 자동 회수한 서버 수를 처리량으로 남긴다.
            add_scheduler_log(db, "UC15", reclaimed)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("유휴 서버 회수 잡 실패")


async def _active_in_use_reservations(db: AsyncSession) -> list[Reservation]:
    """현재 사용 중(IN_USE)인 예약 목록을 가져온다(서버 점유자 식별용)."""
    rows = await db.execute(
        select(Reservation).where(Reservation.status == ReservationStatus.IN_USE.value)
    )
    return list(rows.scalars().all())


async def _handle_reservation(db: AsyncSession, reservation: Reservation, now: datetime) -> int:
    """한 점유 예약에 대해 경고/회수 2단계를 판단해 처리한다(회수했으면 1, 아니면 0)."""
    avg_cpu = await _avg_cpu_usage(db, reservation.server_id, now)
    if not is_idle(avg_cpu):
        return 0  # 유휴가 아니면 경고도 회수도 하지 않는다.

    warned_at = await _latest_warning_time(db, reservation)
    if warned_at is None:
        await _send_warning(db, reservation)  # 1단계: 회수 예고
        return 0
    if now - warned_at >= RECLAIM_GRACE:
        return await _reclaim(db, reservation)  # 2단계: 회수
    return 0


async def _avg_cpu_usage(db: AsyncSession, server_id: int, now: datetime) -> float | None:
    """최근 IDLE_LOOKBACK 구간의 OK 메트릭 평균 CPU 사용률(없으면 None)."""
    return await db.scalar(
        select(func.avg(ServerMetric.cpu_usage)).where(
            ServerMetric.server_id == server_id,
            ServerMetric.status == MetricStatus.OK.value,
            ServerMetric.collected_at >= now - IDLE_LOOKBACK,
        )
    )


async def _latest_warning_time(db: AsyncSession, reservation: Reservation) -> datetime | None:
    """이 예약에 대한 가장 최근 IDLE_WARNING 발송 시각(없으면 None)."""
    # 경고를 reservationId 로 묶는다: 이전 예약의 오래된 경고로 새 예약을 곧장 회수하면
    # 경고→유예→회수 2단계 계약이 깨지므로, 같은 예약의 경고만 인정한다.
    return await db.scalar(
        select(func.max(Notification.created_at)).where(
            Notification.user_id == reservation.user_id,
            Notification.type == _WARNING_TYPE,
            Notification.payload["reservationId"].astext == str(reservation.id),
        )
    )


async def _send_warning(db: AsyncSession, reservation: Reservation) -> None:
    """점유자에게 회수 예고(IDLE_WARNING) 알림 1건을 만든다."""
    db.add(Notification(
        user_id=reservation.user_id,
        type=_WARNING_TYPE,
        message="서버가 유휴 상태입니다. 잠시 후 자동 회수될 수 있습니다.",
        payload={"serverId": reservation.server_id, "reservationId": reservation.id},
    ))
    logger.info("서버 %d 유휴 경고 발송(예약 %d)", reservation.server_id, reservation.id)


async def _reclaim(db: AsyncSession, reservation: Reservation) -> int:
    """유휴 점유를 회수한다: 예약 RECLAIMED, 서버 AVAILABLE, 한도 감소, 회수 알림.

    실제로 회수했으면 1, 서버 상태가 바뀌어 건너뛰면 0 을 반환한다(처리량 집계용).
    """
    # 서버가 여전히 이 예약이 점유(IN_USE)한 상태일 때만 회수한다: 그 사이 다른 요청이
    # 서버를 바꿨다면 우리가 점유자가 아니므로 강제로 AVAILABLE 로 돌려 한도를 잘못 감소시키면 안 된다.
    result = await db.execute(
        update(Server)
        .where(Server.id == reservation.server_id, Server.status == ServerStatus.IN_USE.value)
        .values(status=ServerStatus.AVAILABLE.value, version=Server.version + 1)
    )
    if result.rowcount == 0:
        return 0  # 서버 상태가 바뀌었다 → 예약 전이·한도 감소·회수 알림 모두 건너뛴다.

    reservation.status = ReservationStatus.RECLAIMED.value
    quota = await db.scalar(select(Quota).where(Quota.user_id == reservation.user_id))
    if quota is not None and quota.used > 0:
        quota.used -= 1
    db.add(Notification(
        user_id=reservation.user_id,
        type=_RECLAIM_TYPE,
        message="유휴 상태가 지속되어 서버가 자동 회수되었습니다.",
        payload={"serverId": reservation.server_id, "reservationId": reservation.id},
    ))
    logger.info("서버 %d 자동 회수(예약 %d → RECLAIMED)", reservation.server_id, reservation.id)
    return 1
