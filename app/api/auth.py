"""인증 라우터: 회원가입(UC22), 로그인(UC23), 내 정보 조회(/auth/me)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_user, get_db
from app.core.security import create_access_token
from app.models import User
from app.models.enums import IncidentSeverity, SecurityEventType
from app.schemas.auth import (
    LoginRequest,
    LoginUser,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import (
    AccountLocked,
    EmailAlreadyExists,
    InvalidCredentials,
    TeamNotFound,
    authenticate,
    register_user,
)
from app.services.security_event_service import record_event

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    try:
        return await register_user(db, body)
    except EmailAlreadyExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다.")
    except TeamNotFound:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "존재하지 않는 팀입니다.")


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    client_ip = request.client.host if request.client else None
    try:
        user = await authenticate(db, body.email, body.password)
    except AccountLocked as exc:
        # 계정 잠금 이벤트를 기록하고 커밋한 뒤 예외를 변환한다.
        record_event(
            db,
            event_type=SecurityEventType.ACCOUNT_LOCKED.value,
            severity=IncidentSeverity.WARNING.value,
            source_ip=client_ip,
            identifier=body.email,
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"계정이 잠겼습니다. 해제 예정: {exc.locked_until.isoformat()}",
        )
    except InvalidCredentials:
        # 로그인 실패 이벤트를 기록하고 커밋한 뒤 예외를 변환한다.
        record_event(
            db,
            event_type=SecurityEventType.LOGIN_FAILURE.value,
            severity=IncidentSeverity.INFO.value,
            source_ip=client_ip,
            identifier=body.email,
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다."
        )

    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_min * 60,
        user=LoginUser.model_validate(user),
    )


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
