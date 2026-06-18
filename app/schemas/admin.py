"""관리자 고급 기능 API 스키마."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class ApiSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ResetResult(ApiSchema):
    deleted: int
    message: str


class RunJobResult(ApiSchema):
    job_id: str
    ran_at: datetime
    ok: bool


class SeedAnomalyResult(ApiSchema):
    server_id: int
    inserted: int
    message: str
