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


class HealthTrendPoint(BaseModel):
    """건강점수 이력의 한 점(UC23). 스파크라인용 시점·점수."""

    ts: datetime
    health_score: int = Field(serialization_alias="healthScore")


class HealthTrendResponse(BaseModel):
    """서버 건강·위험 추세(UC23). 잡이 저장한 위험도·이력으로 추세를 노출한다.

    trend 는 저장된 이력의 기울기로 다시 계산한다(IMPROVING/STABLE/DEGRADING).
    drivers 는 위험의 근거 문구 목록이다.
    """

    server_id: int = Field(serialization_alias="serverId")
    health_score: int | None = Field(serialization_alias="healthScore")
    risk_score: float | None = Field(serialization_alias="riskScore")
    trend: str
    eta_to_risk: datetime | None = Field(serialization_alias="etaToRisk")
    history: list[HealthTrendPoint]
    drivers: list[str]


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


# --- 운영 대시보드·가용성(UC21, F21/F22) ---
# 위 AIOps 스키마는 필드마다 serialization_alias 를 적지만, 대시보드 쪽은 필드가 많아
# alias_generator(snake -> camel)로 한 번에 camelCase 로 노출한다.


def _to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class _CamelSchema(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class DashboardSchedulerItem(_CamelSchema):
    uc_id: str
    last_run: datetime | None
    success: bool
    processed: int


class DashboardMetrics(_CamelSchema):
    success_rate: float
    missing: list[str]


class DashboardAutoActions(_CamelSchema):
    reclaimed: int
    expired: int
    auto_rejected: int


class DashboardHealth(_CamelSchema):
    normal: int = Field(serialization_alias="정상")
    caution: int = Field(serialization_alias="주의")
    danger: int = Field(serialization_alias="위험")


class OpsDashboardResponse(_CamelSchema):
    scheduler: list[DashboardSchedulerItem]
    metrics: DashboardMetrics
    auto_actions: DashboardAutoActions
    health: DashboardHealth


class ServerAvailability(_CamelSchema):
    id: int
    uptime: float
    mtbf: float | None
    mttr: float | None
    risk_badge: bool


class AvailabilityResponse(_CamelSchema):
    servers: list[ServerAvailability]
    system_availability: float


# --- 메트릭 히스토리(읽기 전용 시각화, §5) ---


class MetricSeriesPoint(BaseModel):
    """시계열 한 점. 버킷 평균이며 gpu 는 미탑재 노드에서 null."""

    ts: datetime
    cpu: float
    mem: float
    net: float
    gpu: float | None


class ServerMetricSeriesResponse(BaseModel):
    """서버 1대의 사용률 시계열(버킷 평균)."""

    server_id: int = Field(serialization_alias="serverId")
    window: str
    points: list[MetricSeriesPoint]


class MetricHeatmapResponse(BaseModel):
    """서버×시간 히트맵. cells[i][j] = 서버 i 의 j 버킷 평균(없으면 null)."""

    metric: str
    server_ids: list[int] = Field(serialization_alias="servers")
    server_names: list[str] = Field(serialization_alias="serverNames")
    buckets: list[datetime]
    cells: list[list[float | None]]


class ServerAnomalyResponse(BaseModel):
    """서버별 최근 이상 한 건(anomaly_record 직역)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    metric: str
    current_value: float = Field(serialization_alias="currentValue")
    mean: float
    stddev: float
    detected_at: datetime = Field(serialization_alias="detectedAt")
