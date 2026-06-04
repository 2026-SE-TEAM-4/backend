"""예약 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models import User
from app.schemas.reservation import ReservationCreate, ReservationResponse
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
