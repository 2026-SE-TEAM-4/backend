"""운영 대시보드·가용성 집계 로직."""

from datetime import datetime, timedelta, timezone

from collections import defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, AuditLog, Reservation, SchedulerLog, Server, ServerMetric
from app.models.enums import ApprovalStatus, MetricStatus, ReservationStatus
from app.schemas.ops import (
    AvailabilityResponse,
    DashboardAutoActions,
    DashboardHealth,
    DashboardMetrics,
    DashboardSchedulerItem,
    OpsDashboardResponse,
    ServerAvailability,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _availability_stats(statuses: list[str]) -> tuple[int, int, float | None, float | None]:
    uptime_streaks: list[int] = []
    downtime_streaks: list[int] = []
    current_state: str | None = None
    current_count = 0

    for status in statuses:
        state = "down" if status == MetricStatus.MISSING.value else "up"
        if current_state is None:
            current_state = state
            current_count = 1
            continue
        if current_state == state:
            current_count += 1
            continue
        if current_state == "up":
            uptime_streaks.append(current_count)
        else:
            downtime_streaks.append(current_count)
        current_state = state
        current_count = 1

    if current_state == "up":
        uptime_streaks.append(current_count)
    elif current_state == "down":
        downtime_streaks.append(current_count)

    uptime_minutes = sum(uptime_streaks)
    downtime_minutes = sum(downtime_streaks)
    mtbf_minutes = sum(uptime_streaks) / len(uptime_streaks) if uptime_streaks else None
    mttr_minutes = sum(downtime_streaks) / len(downtime_streaks) if downtime_streaks else None
    return uptime_minutes, downtime_minutes, mtbf_minutes, mttr_minutes


async def get_dashboard(session: AsyncSession) -> OpsDashboardResponse:
    since_24h = _now() - timedelta(hours=24)

    scheduler_rows = (
        await session.execute(
            select(SchedulerLog)
            .order_by(SchedulerLog.executed_at.desc())
            .limit(5)
        )
    ).scalars().all()
    scheduler = [
        DashboardSchedulerItem(
            uc_id=row.uc_id,
            last_run=row.executed_at,
            success=row.success,
            processed=row.processed_count,
        )
        for row in scheduler_rows
    ]

    metric_row = (await session.execute(
        select(
            func.count().label("total"),
            func.sum(case((ServerMetric.status == MetricStatus.OK.value, 1), else_=0)).label("success"),
        ).where(ServerMetric.collected_at >= since_24h)
    )).one()
    metric_total = metric_row.total
    metric_success = metric_row.success or 0
    missing_servers = (
        await session.execute(
            select(Server.name)
            .join(ServerMetric, ServerMetric.server_id == Server.id)
            .where(
                Server.deleted_at.is_(None),
                ServerMetric.collected_at >= since_24h,
                ServerMetric.status == MetricStatus.MISSING.value,
            )
            .distinct()
            .order_by(Server.name)
        )
    ).scalars().all()
    success_rate = round((metric_success or 0) / metric_total, 2) if metric_total else 0.0

    reclaimed_count = await session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.created_at >= since_24h,
            AuditLog.action == ReservationStatus.RECLAIMED.value,
        )
    )
    expired_count = await session.scalar(
        select(func.count()).select_from(Reservation).where(
            Reservation.status == ReservationStatus.EXPIRED.value,
            Reservation.end_time >= since_24h,
        )
    )
    auto_rejected_count = await session.scalar(
        select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.status == ApprovalStatus.AUTO_REJECTED.value,
            ApprovalRequest.decided_at >= since_24h,
        )
    )

    health_row = (await session.execute(
        select(
            func.sum(case((Server.health_score >= 80, 1), else_=0)).label("normal"),
            func.sum(case(((Server.health_score >= 50) & (Server.health_score < 80), 1), else_=0)).label("caution"),
            func.sum(case(((Server.health_score < 50) | Server.health_score.is_(None), 1), else_=0)).label("danger"),
        ).where(Server.deleted_at.is_(None))
    )).one()
    normal_count = health_row.normal or 0
    caution_count = health_row.caution or 0
    danger_count = health_row.danger or 0

    return OpsDashboardResponse(
        scheduler=scheduler,
        metrics=DashboardMetrics(
            success_rate=success_rate,
            missing=list(missing_servers),
        ),
        auto_actions=DashboardAutoActions(
            reclaimed=reclaimed_count or 0,
            expired=expired_count or 0,
            auto_rejected=auto_rejected_count or 0,
        ),
        health=DashboardHealth(
            normal=normal_count or 0,
            caution=caution_count or 0,
            danger=danger_count or 0,
        ),
    )


async def get_availability(session: AsyncSession) -> AvailabilityResponse:
    since_24h = _now() - timedelta(hours=24)
    active_ids = set(
        (await session.execute(
            select(ServerMetric.server_id)
            .where(
                ServerMetric.collected_at >= since_24h,
                ServerMetric.status == MetricStatus.OK.value,
            )
            .distinct()
        )).scalars().all()
    )
    servers = (
        await session.execute(
            select(Server)
            .where(Server.deleted_at.is_(None), Server.id.in_(active_ids))
            .order_by(Server.id)
        )
    ).scalars().all()

    # 서버별 N+1 쿼리 대신 단일 쿼리로 전체 로드 후 Python에서 그룹핑
    all_metrics = (
        await session.execute(
            select(ServerMetric.server_id, ServerMetric.status)
            .where(
                ServerMetric.server_id.in_(active_ids),
                ServerMetric.collected_at >= since_24h,
            )
            .order_by(ServerMetric.server_id, ServerMetric.collected_at.asc())
        )
    ).all()
    server_statuses: dict[int, list[str]] = defaultdict(list)
    for server_id, status in all_metrics:
        server_statuses[server_id].append(status)

    items: list[ServerAvailability] = []
    total_uptime = 0
    total_samples = 0

    for server in servers:
        statuses = server_statuses[server.id]
        sample_count = len(statuses)
        uptime_minutes, _downtime_minutes, mtbf_minutes, mttr_minutes = _availability_stats(statuses)
        uptime = round((uptime_minutes / sample_count) * 100, 2) if sample_count else 0.0

        total_uptime += uptime_minutes
        total_samples += sample_count
        items.append(
            ServerAvailability(
                id=server.id,
                uptime=uptime,
                mtbf=round(mtbf_minutes, 2) if mtbf_minutes is not None else None,
                mttr=round(mttr_minutes, 2) if mttr_minutes is not None else None,
                risk_badge=uptime < 95,
            )
        )

    system_availability = round((total_uptime / total_samples) * 100, 2) if total_samples else 0.0
    return AvailabilityResponse(servers=items, system_availability=system_availability)
