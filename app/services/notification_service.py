"""알림 도메인 비즈니스 로직."""

from datetime import datetime, timezone

from fastapi import HTTPException, status
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


async def mark_read(
    notification_id: int, current_user: User, db: AsyncSession
) -> Notification:
    """알림 읽음 처리 [UC03-a]. 본인 알림만 가능. 없으면 404, 타인 알림은 403.

    이미 읽은 알림은 read_at 을 유지한다(멱등).
    """
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "알림을 찾을 수 없습니다.")
    if notification.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "본인 알림만 읽음 처리할 수 있습니다.")

    if notification.read_at is None:
        notification.read_at = datetime.now(tz=timezone.utc)
        await db.commit()
        await db.refresh(notification)
    return notification
