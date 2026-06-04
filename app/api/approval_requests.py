"""승인 요청 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.models import User
from app.schemas.approval_request import ApprovalRequestResponse
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
