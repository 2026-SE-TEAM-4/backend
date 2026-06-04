"""core/security.py 단위 테스트. DB·Redis 없이 순수 로직만 검증한다."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_roundtrip():
    hashed = hash_password("secret123")
    assert hashed != "secret123"  # 평문이 그대로 저장되지 않는다
    assert verify_password("secret123", hashed) is True


def test_verify_rejects_wrong_password():
    hashed = hash_password("secret123")
    assert verify_password("wrong-password", hashed) is False


def test_hash_handles_over_72_bytes():
    # bcrypt 72바이트 초과 입력도 예외 없이 처리되어야 한다(앞 72바이트 사용).
    long_password = "a" * 200
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed) is True


def test_access_token_roundtrip_carries_subject_and_role():
    token = create_access_token(user_id=7, role="STU")
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "STU"


def test_decode_rejects_tampered_token():
    token = create_access_token(user_id=7, role="STU")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token + "tampered")


def test_decode_rejects_expired_token():
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    expired = jwt.encode(
        {"sub": "7", "role": "STU", "exp": past},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)
