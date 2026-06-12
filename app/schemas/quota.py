"""Quota 도메인 요청/응답 스키마."""

from pydantic import BaseModel, Field


class QuotaResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    user_id: int
    user_name: str
    team_id: int
    limit: int
    used: int
    version: int


class QuotaUpdate(BaseModel):
    """팀원 Quota 한도 조정 요청 [UC10]. version 으로 낙관적 잠금을 건다."""

    limit: int = Field(ge=0)
    version: int


class QuotaUpdateResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    limit: int
    used: int
    version: int
