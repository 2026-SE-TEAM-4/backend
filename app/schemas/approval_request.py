"""승인 요청 도메인 응답 스키마."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DecisionRequest(BaseModel):
    action: Literal["APPROVED", "REJECTED"]


class ApprovalRequestResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    requester_id: int
    approver_id: int | None
    server_id: int
    requested_start: datetime
    requested_end: datetime
    reason: str | None
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
