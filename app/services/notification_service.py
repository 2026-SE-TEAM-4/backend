"""알림 도메인 비즈니스 로직."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.notification import Notification


async def list_notifications(current_user: User, db: AsyncSession) -> list[Notification]:
    """본인 알림 목록 조회 [UC03-a].

    최신 알림이 먼저 오도록 created_at 내림차순 정렬한다.
    """
    stmt = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
