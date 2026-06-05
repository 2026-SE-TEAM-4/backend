"""예약 도메인 비즈니스 로직."""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from app.models import Quota, Reservation, Server, User
from app.models.enums import ReservationStatus, ServerStatus, UserRole
from app.schemas.reservation import ReservationCreate, ReservationInstantCreate


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


async def create_instant_reservation(
    current_user: User, req: ReservationInstantCreate, db: AsyncSession
) -> Reservation:
    """즉시 서버 요청 [UC05].

    AVAILABLE 서버 1대를 자동 선정해 낙관적 잠금으로 IN_USE 전환한다.
    health_score 높은 순으로 선정하고, 동점이면 id 오름차순으로 결정론적으로 고른다.
    """
    # Quota 잔여 확인
    quota = await db.scalar(select(Quota).where(Quota.user_id == current_user.id))
    if quota is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Quota 정보가 없습니다.")
    if quota.used >= quota.limit:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Quota가 부족합니다.")

    # AVAILABLE 서버 중 health_score 높은 순으로 1대 선정
    server = await db.scalar(
        select(Server)
        .where(Server.status == ServerStatus.AVAILABLE, Server.deleted_at.is_(None))
        .order_by(Server.health_score.desc().nulls_last(), Server.id.asc())
        .limit(1)
    )
    if server is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "현재 사용 가능한 서버가 없습니다.")

    # 낙관적 잠금: 조회 시점의 version과 일치할 때만 IN_USE로 전환
    locked = await db.execute(
        update(Server)
        .where(Server.id == server.id, Server.version == server.version)
        .values(status=ServerStatus.IN_USE, version=Server.version + 1)
    )
    if locked.rowcount == 0:
        # 선정 직후 다른 트랜잭션이 먼저 점유했음
        raise HTTPException(status.HTTP_409_CONFLICT, "서버 상태가 변경되었습니다. 다시 시도해주세요.")

    now = datetime.now(tz=timezone.utc)
    reservation = Reservation(
        user_id=current_user.id,
        server_id=server.id,
        start_time=now,
        end_time=req.end_time,
        status=ReservationStatus.IN_USE.value,
    )
    db.add(reservation)
    quota.used += 1

    await db.commit()
    await db.refresh(reservation)
    return reservation


async def cancel_reservation(
    reservation_id: int, current_user: User, db: AsyncSession
) -> Reservation:
    """예약 취소 [UC06].

    RESERVED 상태인 본인 예약만 취소 가능. Quota.used 감소 + 서버를 AVAILABLE로 복구.
    """
    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "예약을 찾을 수 없습니다.")

    # STU는 본인 예약만, MGR/ADM은 팀/전체 취소 가능
    if current_user.role == UserRole.STU and reservation.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")
    if current_user.role == UserRole.MGR:
        owner = await db.get(User, reservation.user_id)
        if owner is None or owner.team_id != current_user.team_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")

    if reservation.status != ReservationStatus.RESERVED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "RESERVED 상태의 예약만 취소할 수 있습니다.")

    # 서버를 AVAILABLE로 복구
    await db.execute(
        update(Server)
        .where(Server.id == reservation.server_id)
        .values(status=ServerStatus.AVAILABLE, version=Server.version + 1)
    )

    reservation.status = ReservationStatus.CANCELED.value

    # 예약자의 Quota.used 감소
    quota = await db.scalar(select(Quota).where(Quota.user_id == reservation.user_id))
    if quota is not None and quota.used > 0:
        quota.used -= 1

    await db.commit()
    await db.refresh(reservation)
    return reservation


async def return_reservation(
    reservation_id: int, current_user: User, db: AsyncSession
) -> Reservation:
    """서버 반납 [UC07].

    IN_USE 상태인 예약만 반납 가능. Quota.used 감소 + 서버를 AVAILABLE로 복구.
    """
    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "예약을 찾을 수 없습니다.")

    if current_user.role == UserRole.STU and reservation.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")
    if current_user.role == UserRole.MGR:
        owner = await db.get(User, reservation.user_id)
        if owner is None or owner.team_id != current_user.team_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")

    if reservation.status != ReservationStatus.IN_USE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "IN_USE 상태의 예약만 반납할 수 있습니다.")

    await db.execute(
        update(Server)
        .where(Server.id == reservation.server_id)
        .values(status=ServerStatus.AVAILABLE, version=Server.version + 1)
    )

    reservation.status = ReservationStatus.RETURNED.value

    quota = await db.scalar(select(Quota).where(Quota.user_id == reservation.user_id))
    if quota is not None and quota.used > 0:
        quota.used -= 1

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
