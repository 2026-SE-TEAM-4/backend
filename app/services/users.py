"""사용자 운영 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas.users import UserUnlockResponse


async def unlock_user(session: AsyncSession, user_id: int) -> UserUnlockResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("사용자를 찾을 수 없습니다.")

    user.locked_until = None
    await session.commit()
    await session.refresh(user)
    return UserUnlockResponse(id=user.id, locked_until=user.locked_until)
