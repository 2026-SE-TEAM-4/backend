"""Quota 관련 API 엔드포인트. 팀원별 한도 조정(UC10, F13)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models import User
from app.schemas.quota import QuotaUpdate, QuotaUpdateResponse
from app.services import quota_service

router = APIRouter(prefix="/quotas", tags=["quotas"])


@router.patch("/{quota_id}", response_model=QuotaUpdateResponse)
async def update_quota(
    quota_id: int,
    body: QuotaUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuotaUpdateResponse:
    """팀원 Quota 한도 조정 [UC10].

    MGR: 본인 팀만 / ADM: 모든 팀. STU 403, 없는 Quota 404, 합계 초과·사용량 미만 400,
    version 충돌 409.
    """
    return await quota_service.update_quota(quota_id, body, current_user, db)
