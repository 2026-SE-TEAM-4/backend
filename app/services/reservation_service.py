"""예약 도메인 비즈니스 로직."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from app.models import Quota, Reservation, Server, User
from app.models.enums import ReservationStatus, ServerStatus, UserRole
from app.schemas.reservation import ReservationCreate


async def create_reservation(
    current_user: User, req: ReservationCreate, db: AsyncSession
) -> Reservation:
    """서버 예약 요청(예약형) [UC04].

    Quota 잔여 확인 → 낙관적 잠금으로 서버 점유 → Reservation 생성 +
    Quota.used 증가를 단일 트랜잭션으로 처리한다.
    """
    # 서버 존재·상태 확인
    server = await db.get(Server, req.server_id)
    if server is None or server.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "서버를 찾을 수 없습니다.")
    if server.status != ServerStatus.AVAILABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "예약 가능한 서버가 아닙니다.")

    # Quota 잔여 확인
    quota = await db.scalar(select(Quota).where(Quota.user_id == current_user.id))
    if quota is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Quota 정보가 없습니다.")
    if quota.used >= quota.limit:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Quota가 부족합니다.")

    # 낙관적 잠금: 조회 시점의 version과 일치할 때만 RESERVED로 전환
    locked = await db.execute(
        update(Server)
        .where(Server.id == server.id, Server.version == server.version)
        .values(status=ServerStatus.RESERVED, version=Server.version + 1)
    )
    if locked.rowcount == 0:
        # 다른 트랜잭션이 먼저 점유했음
        raise HTTPException(status.HTTP_409_CONFLICT, "서버 상태가 변경되었습니다. 다시 시도해주세요.")

    reservation = Reservation(
        user_id=current_user.id,
        server_id=req.server_id,
        start_time=req.start_time,
        end_time=req.end_time,
        status=ReservationStatus.RESERVED.value,
    )
    db.add(reservation)
    quota.used += 1

    await db.commit()
    await db.refresh(reservation)
    return reservation


async def list_reservations(current_user: User, db: AsyncSession) -> list[Reservation]:
    """역할별 예약 목록 조회 [UC02].

    STU는 본인 예약만, MGR는 같은 팀 전체, ADM은 시스템 전체를 본다.
    """
    if current_user.role == UserRole.STU:
        stmt = select(Reservation).where(Reservation.user_id == current_user.id)
    elif current_user.role == UserRole.MGR:
        # 팀원 전체 예약을 보려면 user 테이블과 조인해 team_id로 필터링한다
        stmt = (
            select(Reservation)
            .join(User, Reservation.user_id == User.id)
            .where(User.team_id == current_user.team_id)
        )
    else:  # ADM
        stmt = select(Reservation)

    result = await db.execute(stmt)
    return list(result.scalars().all())
