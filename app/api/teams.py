"""팀 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models import Team, User
from app.schemas.quota import QuotaResponse
from app.schemas.team import TeamItem, TeamListResponse
from app.services import quota_service

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=TeamListResponse)
async def list_teams(db: AsyncSession = Depends(get_db)) -> TeamListResponse:
    """팀 목록 조회. 회원가입 팀 선택용이라 인증 없이 id·name·code 만 노출한다."""
    rows = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
    return TeamListResponse(teams=[TeamItem.model_validate(t) for t in rows])


@router.get("/{team_id}/quotas", response_model=list[QuotaResponse])
async def get_team_quotas(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[QuotaResponse]:
    """팀원별 Quota 조회 [UC10].

    MGR: 본인 팀만 / ADM: 모든 팀. STU 접근 시 403, 존재하지 않는 팀 404.
    """
    return await quota_service.list_team_quotas(team_id, current_user, db)
