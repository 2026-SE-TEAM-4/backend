"""여러 도메인이 공유하는 FastAPI 의존성: DB 세션, 현재 사용자, 권한 게이트."""

from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models import User
from app.models.enums import IncidentSeverity, SecurityEventType
from app.services.security_event_service import record_event

# 토큰이 없을 때 직접 401을 내기 위해 auto_error를 끈다(기본값은 403).
_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "인증이 필요합니다.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 토큰입니다.")

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 토큰입니다.")

    user = await db.get(User, int(subject))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 토큰입니다.")
    return user


def require_role(*roles: str):
    """지정 역할만 통과시키는 의존성. 후속 UC들의 권한 게이트로 재사용한다."""

    async def checker(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if user.role not in roles:
            # 권한 거부 이벤트를 기록하고 커밋한 뒤 403을 올린다.
            client_ip = request.client.host if request.client else None
            record_event(
                db,
                event_type=SecurityEventType.ACCESS_DENIED.value,
                severity=IncidentSeverity.WARNING.value,
                actor_id=user.id,
                source_ip=client_ip,
                detail={"path": request.url.path},
            )
            await db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")
        return user

    return checker
