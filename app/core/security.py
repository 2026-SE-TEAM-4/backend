"""비밀번호 해시(bcrypt)와 액세스 토큰(JWT) 발급·검증.

순수 함수만 둔다. DB·FastAPI를 알지 않으므로 단위 테스트가 쉽다.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

# bcrypt는 입력의 앞 72바이트만 사용한다. 초과분을 미리 잘라 ValueError를 피한다.
_BCRYPT_MAX_BYTES = 72
_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(pw, hashed.encode("utf-8"))


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_min),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """서명·만료·알고리즘을 검증한다. 실패 시 PyJWT 예외를 그대로 올린다."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
