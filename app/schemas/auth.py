"""인증 입출력 스키마.

요청은 camelCase(teamId)와 snake_case 둘 다 받고, 응답은 camelCase로 노출한다.
비밀번호·해시는 어떤 응답에도 포함하지 않는다(보안).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: UserRole
    team_id: int = Field(alias="teamId")


class UserResponse(BaseModel):
    """회원가입 결과 요약."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: UserRole
    team_id: int = Field(serialization_alias="teamId")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class LoginUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: UserRole
    team_id: int = Field(serialization_alias="teamId")


class TokenResponse(BaseModel):
    access_token: str = Field(serialization_alias="accessToken")
    token_type: str = Field(default="bearer", serialization_alias="tokenType")
    expires_in: int = Field(serialization_alias="expiresIn")
    user: LoginUser


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: UserRole
    team_id: int = Field(serialization_alias="teamId")
    locked_until: datetime | None = Field(default=None, serialization_alias="lockedUntil")
