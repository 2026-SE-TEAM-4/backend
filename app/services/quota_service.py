"""Quota 도메인 비즈니스 로직."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Quota, Team, User
from app.models.enums import UserRole
from app.schemas.quota import QuotaUpdate


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


async def update_quota(
    quota_id: int, body: QuotaUpdate, current_user: User, db: AsyncSession
) -> Quota:
    """팀원 Quota 한도 조정 [UC10].

    MGR은 본인 팀만, ADM은 모든 팀. STU는 403. 한도는 현재 사용량 미만으로 못 낮추고
    (400, UC10-E2), 팀 합계 한도를 넘을 수 없다(400, UC10-E1). version 불일치는 409(UC10-E3).
    """
    if current_user.role == UserRole.STU:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")

    quota = await db.get(Quota, quota_id)
    if quota is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quota를 찾을 수 없습니다.")

    if current_user.role == UserRole.MGR and current_user.team_id != quota.team_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "본인 팀의 Quota만 조정할 수 있습니다.")

    if body.version != quota.version:
        raise HTTPException(status.HTTP_409_CONFLICT, "다른 곳에서 먼저 수정되었습니다. 새로고침 후 다시 시도하세요.")

    if body.limit < quota.used:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "현재 사용량보다 낮은 한도로 조정할 수 없습니다."
        )

    # 팀 합계 한도 검증(설정된 경우에만). 본인 외 팀원 한도 합 + 새 한도 <= 팀 총한도.
    team = await db.get(Team, quota.team_id)
    if team is not None and team.total_quota_limit > 0:
        others_total = await db.scalar(
            select(func.coalesce(func.sum(Quota.limit), 0)).where(
                Quota.team_id == quota.team_id, Quota.id != quota_id
            )
        )
        if (others_total or 0) + body.limit > team.total_quota_limit:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "팀 전체 한도 합계를 초과합니다."
            )

    quota.limit = body.limit
    quota.version += 1
    await db.commit()
    await db.refresh(quota)
    return quota
