"""알림 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models import User
from app.schemas.notification import NotificationResponse
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
async def get_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    """본인 알림 목록 조회 [UC03-a].

    모든 역할이 접근 가능하며 본인 알림만 반환한다.
    """
    return await notification_service.list_notifications(current_user, db)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def read_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    """알림 읽음 처리 [UC03-a]. 본인 알림만. 없으면 404, 타인 알림 403."""
    return await notification_service.mark_read(notification_id, current_user, db)
