"""관리자 고급 기능 라우터.

데모·실 테스트를 위한 운영 데이터 초기화 엔드포인트를 제공한다.
모든 엔드포인트는 ADM 전용이다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.models import User
from app.schemas.admin import ResetResult
from app.services import admin as admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset/availability", response_model=ResetResult)
async def reset_availability(
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """가용성 히스토리 초기화 [고급].

    ServerMetric과 ServerHealthHistory를 전부 삭제한다.
    이후 스케줄러가 다시 수집하면 히스토리가 새로 쌓인다.
    """
    return await admin_service.reset_availability(db)


@router.post("/reset/aiops", response_model=ResetResult)
async def reset_aiops(
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """AIOps 데이터 초기화 [고급].

    Incident, AnomalyRecord, IncidentSummary, Forecast, SchedulerLog를 삭제한다.
    """
    return await admin_service.reset_aiops(db)


@router.post("/reset/notifications", response_model=ResetResult)
async def reset_notifications(
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """알림·감사 로그 초기화 [고급].

    Notification과 AuditLog를 삭제한다.
    """
    return await admin_service.reset_notifications(db)


@router.post("/reset/reservations", response_model=ResetResult)
async def reset_reservations(
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """예약·승인·대기열 초기화 [고급].

    Reservation, ApprovalRequest, QueueEntry, MaintenanceSchedule을 삭제한다.
    """
    return await admin_service.reset_reservations(db)


@router.post("/reset/all", response_model=ResetResult)
async def reset_all(
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """전체 운영 데이터 초기화 [고급].

    마스터 데이터(User, Team, Quota, Server)를 제외한 모든 운영 데이터를 삭제한다.
    데모 초기 상태로 되돌릴 때 사용한다.
    """
    return await admin_service.reset_all(db)
