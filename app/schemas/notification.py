"""알림 도메인 응답 스키마."""

from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    user_id: int
    type: str
    message: str
    payload: dict | None
    read_at: datetime | None
    created_at: datetime
