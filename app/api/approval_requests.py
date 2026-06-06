"""승인 요청 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.models import User
from app.schemas.approval_request import ApprovalRequestResponse, DecisionRequest
from app.services import approval_service

router = APIRouter(prefix="/approval-requests", tags=["approval-requests"])


@router.get("", response_model=list[ApprovalRequestResponse])
async def get_approval_requests(
    current_user: User = Depends(require_role("MGR", "ADM")),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRequestResponse]:
    """허가함 목록 조회 [UC09].

    MGR: 팀 요청만 / ADM: 전체 요청. STU 접근 시 403.
    """
    return await approval_service.list_approval_requests(current_user, db)


@router.post("/{approval_id}/decision", response_model=ApprovalRequestResponse)
async def decide_approval_request(
    approval_id: int,
    req: DecisionRequest,
    current_user: User = Depends(require_role("MGR", "ADM")),
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestResponse:
    """초과 요청 승인/거절 [UC09].

    PENDING → APPROVED/REJECTED 전환. decided_at·decided_by·approver_id 기록.
    APPROVED 시 Reservation 생성 및 서버 RESERVED 전환.
    """
    return await approval_service.decide_approval_request(approval_id, req, current_user, db)
