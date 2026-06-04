"""회원가입(UC22)·로그인(UC23) 도메인 로직.

FastAPI를 알지 않는다(tree.md). HTTP 매핑은 api/auth.py가 하고,
여기서는 도메인 예외만 올린다. 로그인 실패 누적 잠금은 UC20과 같은
user.locked_until 컬럼을 공유한다(설계 D4).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.redis import increment_login_fail, reset_login_fail
from app.core.security import hash_password, verify_password
from app.models import Team, User
from app.schemas.auth import RegisterRequest


class EmailAlreadyExists(Exception):
    """이미 가입된 이메일."""


class TeamNotFound(Exception):
    """가입 시 지정한 팀이 존재하지 않음."""


class InvalidCredentials(Exception):
    """이메일 미존재 또는 비밀번호 불일치(열거 방지를 위해 구분하지 않음)."""


class AccountLocked(Exception):
    """계정이 잠긴 상태. 해제 예정 시각을 함께 전달한다."""

    def __init__(self, locked_until: datetime) -> None:
        super().__init__("account locked")
        self.locked_until = locked_until


async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing is not None:
        raise EmailAlreadyExists

    team = await db.get(Team, data.team_id)
    if team is None:
        raise TeamNotFound

    user = User(
        name=data.name,
        email=data.email,
        role=data.role.value,
        team_id=data.team_id,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    """성공 시 User를 돌려준다. 실패는 InvalidCredentials/AccountLocked로 올린다."""
    user = await db.scalar(select(User).where(User.email == email))
    now = datetime.now(timezone.utc)

    if user is not None and user.locked_until is not None and user.locked_until > now:
        raise AccountLocked(user.locked_until)

    password_ok = (
        user is not None
        and user.hashed_password is not None
        and verify_password(password, user.hashed_password)
    )
    if not password_ok:
        # 존재하는 계정의 비밀번호 실패만 카운트한다. 임계 도달 시 잠근다.
        if user is not None:
            count = await increment_login_fail(email)
            if count >= settings.login_fail_max:
                user.locked_until = now + timedelta(minutes=settings.login_lock_min)
                await db.commit()
                raise AccountLocked(user.locked_until)
        raise InvalidCredentials

    await reset_login_fail(email)
    return user
