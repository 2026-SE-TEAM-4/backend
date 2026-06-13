"""서버 관리 API 스키마."""

from datetime import datetime
from ipaddress import ip_address
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class ApiSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ServerSpec(ApiSchema):
    cpu_cores: int
    ram_gb: int
    gpu_model: str | None = None


class ServerCreate(ApiSchema):
    name: str = Field(min_length=1, max_length=100)
    ip: str = Field(min_length=1, max_length=45)
    cpu_cores: int = Field(gt=0)
    ram_gb: int = Field(gt=0)
    gpu_model: str | None = Field(default=None, max_length=100)
    group_name: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("group", "groupName"),
    )
    start_in_maintenance: bool = False

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, value: str) -> str:
        ip_address(value)
        return value


class ServerCreateResponse(ApiSchema):
    id: int
    status: str
    version: int


class LatestMetric(ApiSchema):
    cpu_usage: float
    mem_usage: float
    net_usage: float
    gpu_usage: float | None = None
    status: str
    collected_at: datetime


class ServerDetailResponse(ApiSchema):
    id: int
    name: str
    status: str
    spec: ServerSpec
    health_score: int | None
    # 프런트 카드/상세에서 함께 쓰는 서버 메타·위험 지표.
    ip: str | None = None
    group_name: str | None = None
    risk_score: float | None = None
    eta_to_risk: datetime | None = None
    occupant: str | None = None
    latest_metric: LatestMetric | None = None


# 목록과 상세가 같은 표현을 공유한다. 별도 필드는 두지 않는다.
class ServerListItem(ServerDetailResponse):
    pass


class ServerListResponse(ApiSchema):
    servers: list[ServerListItem]


class AlternativeSpec(ApiSchema):
    cpu_cores: int
    ram_gb: int


class ServerAlternative(ApiSchema):
    id: int
    name: str
    spec: AlternativeSpec


class ServerAlternativeResponse(ApiSchema):
    alternatives: list[ServerAlternative]


class MaintenanceCreate(ApiSchema):
    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=500)
    recurring_rule: str | None = Field(default=None, max_length=200)
    force: bool = False

    @field_validator("end_at")
    @classmethod
    def validate_range(cls, end_at: datetime, info):
        start_at = info.data.get("start_at")
        if start_at is not None and end_at <= start_at:
            raise ValueError("endAt은 startAt보다 뒤여야 한다")
        return end_at


class MaintenanceCreateResponse(ApiSchema):
    maintenance_id: int


class ServerDeleteResponse(ApiSchema):
    id: int
    deleted_at: datetime


ServerSort = Literal["id", "name", "status", "health_score", "created_at"]
