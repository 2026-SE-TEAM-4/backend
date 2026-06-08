"""운영 API 스키마."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class ApiSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DashboardSchedulerItem(ApiSchema):
    uc_id: str
    last_run: datetime | None
    success: bool
    processed: int


class DashboardMetrics(ApiSchema):
    success_rate: float
    missing: list[str]


class DashboardAutoActions(ApiSchema):
    reclaimed: int
    expired: int
    auto_rejected: int


class DashboardHealth(ApiSchema):
    normal: int = Field(serialization_alias="정상")
    caution: int = Field(serialization_alias="주의")
    danger: int = Field(serialization_alias="위험")


class OpsDashboardResponse(ApiSchema):
    scheduler: list[DashboardSchedulerItem]
    metrics: DashboardMetrics
    auto_actions: DashboardAutoActions
    health: DashboardHealth


class ServerAvailability(ApiSchema):
    id: int
    uptime: float
    mtbf: float | None
    mttr: float | None
    risk_badge: bool


class AvailabilityResponse(ApiSchema):
    servers: list[ServerAvailability]
    system_availability: float
