"""예약 도메인 요청/응답 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class ReservationCreate(BaseModel):
    model_config = {"populate_by_name": True}

    server_id: int = Field(alias="serverId")
    start_time: datetime = Field(alias="startTime")
    end_time: datetime = Field(alias="endTime")


class ReservationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    user_id: int
    server_id: int
    start_time: datetime
    end_time: datetime
    status: str
    created_at: datetime
