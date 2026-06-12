"""승인 요청 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.models import User
from app.schemas.approval_request import (
    ApprovalRequestResponse,
    CreateApprovalRequest,
    CreateApprovalResponse,
    DecisionRequest,
)
from app.services import approval_service

router = APIRouter(prefix="/approval-requests", tags=["approval-requests"])


@router.post("", response_model=CreateApprovalResponse, status_code=http_status.HTTP_201_CREATED)
async def create_approval_request(
    req: CreateApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateApprovalResponse:
    """Quota 초과 승인 요청 생성 [UC08 / F09].

    요청자는 현재 사용자이며, 예약 생성(F04)과 동일하게 역할 제한이 없다(인증만 요구).
    서버가 없거나 삭제됐으면 404, 동일 서버 PENDING 중복이면 409.
    """
    approval = await approval_service.create_approval_request(req, current_user, db)
    return CreateApprovalResponse(approvalRequestId=approval.id, status="PENDING")


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
