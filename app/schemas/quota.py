"""Quota 도메인 응답 스키마."""

from pydantic import BaseModel


class QuotaResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    user_id: int
    team_id: int
    limit: int
    used: int
