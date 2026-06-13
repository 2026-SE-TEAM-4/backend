"""보안 관제 도메인 응답·요청 스키마(UC26·UC27·UC28). 응답은 camelCase 로 노출한다."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SecurityEventResponse(BaseModel):
    """보안 이벤트 한 건(목록용)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str = Field(serialization_alias="eventType")
    severity: str
    actor_id: int | None = Field(serialization_alias="actorId")
    source_ip: str | None = Field(serialization_alias="sourceIp")
    identifier: str | None
    target_type: str | None = Field(serialization_alias="targetType")
    target_id: str | None = Field(serialization_alias="targetId")
    detail: dict | None
    occurred_at: datetime = Field(serialization_alias="occurredAt")


class SecurityAlertResponse(BaseModel):
    """보안 경보 한 건(목록·해결 공용)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_type: str = Field(serialization_alias="alertType")
    severity: str
    status: str
    subject: str
    event_count: int = Field(serialization_alias="eventCount")
    message: str
    started_at: datetime = Field(serialization_alias="startedAt")
    resolved_at: datetime | None = Field(serialization_alias="resolvedAt")
    resolved_by: int | None = Field(serialization_alias="resolvedBy")


class SecuritySummaryResponse(BaseModel):
    """보안 KPI 집계(대시보드 상단 타일용)."""

    today_events: int = Field(serialization_alias="todayEvents")
    open_alerts: int = Field(serialization_alias="openAlerts")
    critical_alerts: int = Field(serialization_alias="criticalAlerts")
    brute_force_suspects: int = Field(serialization_alias="bruteForceSuspects")


class SimulateRequest(BaseModel):
    """보안 시뮬레이션 요청. scenario 에 따라 임계를 넘기는 가짜 이벤트를 삽입한다."""

    scenario: str  # brute_force | access_abuse | agent_down | admin_abuse


class SimulateResponse(BaseModel):
    """시뮬레이션 결과."""

    inserted: int
    scenario: str
