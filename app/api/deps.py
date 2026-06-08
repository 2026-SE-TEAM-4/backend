"""FastAPI 공통 의존성."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@dataclass(frozen=True)
class AuthContext:
    user_id: int
    role: str


async def get_auth_context(
    auth_user_id: Annotated[int | None, Header(alias="X-User-Id")] = None,
    user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
) -> AuthContext:
    if auth_user_id is None or user_role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다.",
        )
    return AuthContext(user_id=auth_user_id, role=user_role)


async def require_admin(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    if auth.role != "ADM":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한이 없습니다.",
        )
    return auth
