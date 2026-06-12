"""운영(ops) 도메인 응답 스키마(UC24). 응답은 camelCase 로 노출한다."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IncidentResponse(BaseModel):
    """인시던트 요약(목록·상세 공용)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    severity: str
    status: str
    anomaly_count: int = Field(serialization_alias="anomalyCount")
    server_ids: list[int] = Field(serialization_alias="serverIds")
    started_at: datetime = Field(serialization_alias="startedAt")
    resolved_at: datetime | None = Field(serialization_alias="resolvedAt")


class IncidentListResponse(BaseModel):
    """인시던트 목록 + 노이즈 감소율."""

    noise_reduction_rate: float = Field(serialization_alias="noiseReductionRate")
    incidents: list[IncidentResponse]


class AnomalyResponse(BaseModel):
    """인시던트에 묶인 개별 이상."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    server_id: int = Field(serialization_alias="serverId")
    metric: str
    current_value: float = Field(serialization_alias="currentValue")
    mean: float
    stddev: float
    detected_at: datetime = Field(serialization_alias="detectedAt")


class IncidentDetailResponse(BaseModel):
    """인시던트 상세 + 묶인 이상 목록."""

    incident: IncidentResponse
    anomalies: list[AnomalyResponse]
