"""사용자 운영 API 라우터. 계정 잠금 해제(UC20, F20)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas.users import UserUnlockResponse
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/{user_id}/unlock", response_model=UserUnlockResponse)
async def unlock_user(
    user_id: int,
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> UserUnlockResponse:
    """계정 잠금 해제 [UC20]. 비정상 접근 오탐을 관리자가 푼다. 없는 사용자는 404."""
    try:
        return await user_service.unlock_user(db, user_id)
    except NotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
