"""운영(ops) 도메인 응답 스키마(UC24·UC22). 응답은 camelCase 로 노출한다."""

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


class ForecastResponse(BaseModel):
    """용량·수요 예측 결과(UC22). 가장 최근 저장본을 그대로 노출한다."""

    model_config = ConfigDict(from_attributes=True)

    server_id: int | None = Field(serialization_alias="serverId")
    metric: str
    generated_at: datetime = Field(serialization_alias="generatedAt")
    saturation_at: datetime | None = Field(serialization_alias="saturationAt")
    confidence: float
    # 향후 시점별 예측점 목록 [{ts, yhat, lower, upper}]. JSONB 를 그대로 전달한다.
    horizon: list[dict]


class IncidentSummaryResponse(BaseModel):
    """인시던트 LLM 원인 요약(UC25). 잡이 저장한 자문용 요약을 그대로 노출한다.

    LLM 이 작성한 분석 결과로, 사람이 검토해야 한다(자동 조치 없음). root_causes 는
    [{cause, evidence}], recommendations 는 [{action, rationale}] JSONB 를 그대로 전달한다.
    """

    # 응답 필드명 `model`(요약을 만든 모델 id)이 Pydantic 의 model_ 예약 접두어와 겹쳐
    # 경고가 나므로, 이 스키마에서는 보호 네임스페이스를 비워 충돌을 없앤다.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    incident_id: int = Field(serialization_alias="incidentId")
    generated_at: datetime = Field(serialization_alias="generatedAt")
    model: str
    situation: str
    root_causes: list[dict] = Field(serialization_alias="rootCauses")
    recommendations: list[dict]
