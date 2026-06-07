"""예약 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models import User
from app.schemas.reservation import ReservationCreate, ReservationInstantCreate, ReservationResponse
from app.services import reservation_service

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.get("", response_model=list[ReservationResponse])
async def get_reservations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReservationResponse]:
    """예약 현황 조회 [UC02].

    STU: 본인 예약만 / MGR: 팀 전체 예약 / ADM: 시스템 전체 예약
    """
    return await reservation_service.list_reservations(current_user, db)


@router.post("", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    body: ReservationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    """서버 예약 요청(예약형) [UC04].

    Quota 부족 시 422, 서버 동시 점유 충돌 시 409.
    """
    return await reservation_service.create_reservation(current_user, body, db)


@router.post("/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    """예약 취소 [UC06].

    RESERVED 상태만 취소 가능. STU: 본인만 / MGR: 팀 예약 / ADM: 전체.
    """
    return await reservation_service.cancel_reservation(reservation_id, current_user, db)


@router.post("/{reservation_id}/return", response_model=ReservationResponse)
async def return_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    """서버 반납 [UC07].

    IN_USE 상태만 반납 가능. STU: 본인만 / MGR: 팀 예약 / ADM: 전체.
    """
    return await reservation_service.return_reservation(reservation_id, current_user, db)


@router.post("/instant", response_model=ReservationResponse, status_code=201)
async def create_instant_reservation(
    body: ReservationInstantCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    """즉시 서버 요청 [UC05].

    AVAILABLE 서버 자동 선정 후 IN_USE 전환. Quota 부족 시 422, 가용 서버 없거나 충돌 시 409.
    """
    return await reservation_service.create_instant_reservation(current_user, body, db)
