"""관리자 고급 기능 서비스 로직.

데모·테스트를 위한 운영 데이터 초기화 기능을 제공한다.
마스터 데이터(User, Team, Quota, Server)는 건드리지 않는다.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AnomalyRecord,
    ApprovalRequest,
    AuditLog,
    Forecast,
    Incident,
    IncidentSummary,
    MaintenanceSchedule,
    Notification,
    QueueEntry,
    Reservation,
    SchedulerLog,
    SecurityAlert,
    SecurityEvent,
    ServerHealthHistory,
    ServerMetric,
)
from app.schemas.admin import ResetResult


async def _count_and_delete(session: AsyncSession, *models) -> int:
    total = 0
    for model in models:
        n = await session.scalar(select(func.count()).select_from(model)) or 0
        total += n
        await session.execute(delete(model))
    return total


async def reset_availability(session: AsyncSession) -> ResetResult:
    """가용성 히스토리 초기화 — ServerMetric과 ServerHealthHistory를 삭제한다."""
    deleted = await _count_and_delete(session, ServerMetric, ServerHealthHistory)
    await session.commit()
    return ResetResult(deleted=deleted, message=f"가용성 히스토리 {deleted}건 삭제됨")


async def reset_aiops(session: AsyncSession) -> ResetResult:
    """AIOps 데이터 초기화 — Incident 관련 데이터·예측·스케줄러 로그를 삭제한다.

    FK 순서: IncidentSummary·AnomalyRecord → Incident 순으로 삭제해야 한다.
    """
    deleted = await _count_and_delete(
        session,
        IncidentSummary,
        AnomalyRecord,
        Incident,
        Forecast,
        SchedulerLog,
    )
    await session.commit()
    return ResetResult(deleted=deleted, message=f"AIOps 데이터 {deleted}건 삭제됨")


async def reset_notifications(session: AsyncSession) -> ResetResult:
    """알림·감사 로그 초기화 — Notification과 AuditLog를 삭제한다."""
    deleted = await _count_and_delete(session, Notification, AuditLog)
    await session.commit()
    return ResetResult(deleted=deleted, message=f"알림·감사 로그 {deleted}건 삭제됨")


async def reset_reservations(session: AsyncSession) -> ResetResult:
    """예약·승인·대기열 초기화 — 예약 트랜잭션 데이터를 삭제한다."""
    deleted = await _count_and_delete(
        session,
        ApprovalRequest,
        QueueEntry,
        Reservation,
        MaintenanceSchedule,
    )
    await session.commit()
    return ResetResult(deleted=deleted, message=f"예약·승인·대기열 {deleted}건 삭제됨")


async def reset_all(session: AsyncSession) -> ResetResult:
    """전체 운영 데이터 초기화.

    마스터 데이터(User, Team, Quota, Server) 제외 모든 운영 데이터를 삭제한다.
    FK 의존 순서를 지켜 삭제한다. 보안 데이터(SecurityAlert·SecurityEvent)도 포함한다.
    """
    deleted = await _count_and_delete(
        session,
        # 보안 경보 먼저(user FK 참조만, SecurityEvent 와 FK 관계 없음).
        SecurityAlert,
        SecurityEvent,
        IncidentSummary,
        AnomalyRecord,
        Incident,
        Forecast,
        SchedulerLog,
        AuditLog,
        Notification,
        MaintenanceSchedule,
        ApprovalRequest,
        QueueEntry,
        Reservation,
        ServerHealthHistory,
        ServerMetric,
    )
    await session.commit()
    return ResetResult(deleted=deleted, message=f"전체 운영 데이터 {deleted}건 삭제됨")


async def reset_security(session: AsyncSession) -> ResetResult:
    """보안 데이터 초기화 — SecurityAlert·SecurityEvent 를 삭제한다."""
    deleted = await _count_and_delete(session, SecurityAlert, SecurityEvent)
    await session.commit()
    return ResetResult(deleted=deleted, message=f"보안 데이터 {deleted}건 삭제됨")
