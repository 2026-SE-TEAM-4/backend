"""사용자 운영 API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_session, require_admin
from app.core.exceptions import NotFoundError
from app.schemas.users import UserUnlockResponse
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/{user_id}/unlock", response_model=UserUnlockResponse)
async def unlock_user(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AuthContext, Depends(require_admin)],
) -> UserUnlockResponse:
    try:
        return await user_service.unlock_user(session, user_id)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
