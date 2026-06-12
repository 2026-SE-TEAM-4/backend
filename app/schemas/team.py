"""팀 조회 스키마. 회원가입 팀 선택 드롭다운용 최소 정보."""

from pydantic import BaseModel, ConfigDict


class TeamItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str


class TeamListResponse(BaseModel):
    teams: list[TeamItem]
