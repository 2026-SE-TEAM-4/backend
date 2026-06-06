"""승인 요청 도메인 비즈니스 로직."""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, Quota, Reservation, Server, User
from app.models.enums import ApprovalStatus, ReservationStatus, ServerStatus, UserRole
from app.schemas.approval_request import DecisionRequest


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


async def decide_approval_request(
    approval_id: int,
    req: DecisionRequest,
    current_user: User,
    db: AsyncSession,
) -> ApprovalRequest:
    """초과 요청 승인/거절 [UC09].

    MGR: 같은 팀 요청만 결정 가능. ADM: 전체 결정 가능.
    PENDING 상태인 요청만 처리한다.
    APPROVED 시 서버를 RESERVED로 전환하고 Reservation을 생성한다(Quota limit 체크 없이).
    """
    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "승인 요청을 찾을 수 없습니다.")

    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "PENDING 상태인 요청만 결정할 수 있습니다.")

    # MGR은 같은 팀 요청자의 요청만 결정 가능
    if current_user.role == UserRole.MGR:
        requester = await db.get(User, approval.requester_id)
        if requester is None or requester.team_id != current_user.team_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다.")

    now = datetime.now(tz=timezone.utc)

    if req.action == ApprovalStatus.APPROVED.value:
        server = await db.get(Server, approval.server_id)
        if server is None or server.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "서버를 찾을 수 없습니다.")
        if server.status != ServerStatus.AVAILABLE:
            raise HTTPException(status.HTTP_409_CONFLICT, "현재 예약 가능한 서버가 아닙니다.")

        # 낙관적 잠금으로 서버 RESERVED 전환
        locked = await db.execute(
            update(Server)
            .where(Server.id == server.id, Server.version == server.version)
            .values(status=ServerStatus.RESERVED, version=Server.version + 1)
        )
        if locked.rowcount == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "서버 상태가 변경되었습니다. 다시 시도해주세요.")

        reservation = Reservation(
            user_id=approval.requester_id,
            server_id=approval.server_id,
            start_time=approval.requested_start,
            end_time=approval.requested_end,
            status=ReservationStatus.RESERVED.value,
        )
        db.add(reservation)

        # Quota 초과 승인이므로 limit 체크 없이 used만 증가
        quota = await db.scalar(select(Quota).where(Quota.user_id == approval.requester_id))
        if quota is not None:
            quota.used += 1

    approval.status = req.action
    approval.decided_at = now
    approval.decided_by = current_user.name
    approval.approver_id = current_user.id

    await db.commit()
    await db.refresh(approval)
    return approval
