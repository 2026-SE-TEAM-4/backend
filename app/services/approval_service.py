"""승인 요청 도메인 비즈니스 로직."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, User
from app.models.enums import UserRole


async def list_approval_requests(
    current_user: User, db: AsyncSession
) -> list[ApprovalRequest]:
    """허가함 목록 조회 [UC09].

    MGR은 같은 팀 소속 요청자의 승인 요청만, ADM은 전체를 본다.
    STU는 라우터 레이어에서 이미 차단되므로 여기에 도달하지 않는다.
    """
    if current_user.role == UserRole.MGR:
        # requester가 같은 팀 소속인 요청만 조회
        stmt = (
            select(ApprovalRequest)
            .join(User, ApprovalRequest.requester_id == User.id)
            .where(User.team_id == current_user.team_id)
        )
    else:  # ADM
        stmt = select(ApprovalRequest)

    result = await db.execute(stmt)
    return list(result.scalars().all())
