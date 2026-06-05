"""Quota 도메인 비즈니스 로직."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models import Quota, Team, User
from app.models.enums import UserRole


async def list_team_quotas(
    team_id: int, current_user: User, db: AsyncSession
) -> list[Quota]:
    """팀원별 Quota 조회 [UC10].

    MGR은 본인 팀만, ADM은 모든 팀 조회 가능. STU는 403.
    """
    if current_user.role == UserRole.STU:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")

    # MGR은 본인 팀 이외의 팀 조회 불가
    if current_user.role == UserRole.MGR and current_user.team_id != team_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "본인 팀의 Quota만 조회할 수 있습니다.")

    # 팀 존재 여부 확인
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "팀을 찾을 수 없습니다.")

    result = await db.execute(
        select(Quota).where(Quota.team_id == team_id)
    )
    return list(result.scalars().all())
