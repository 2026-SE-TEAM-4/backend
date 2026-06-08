"""메트릭 수집·이상 탐지·건강 점수·자동 회수 로직."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import urlopen

from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AnomalyRecord,
    AuditLog,
    Notification,
    Reservation,
    SchedulerLog,
    Server,
    ServerMetric,
    User,
)
from app.models.enums import MetricStatus, ReservationStatus, ServerStatus, UserRole


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _usage_value(data: dict, key: str) -> float:
    value = float(data[key])
    if value < 0 or value > 100:
        raise ValueError(f"{key}는 0부터 100 사이여야 합니다.")
    return value


def _metric_status(data: dict) -> str:
    status = data.get("status", MetricStatus.OK.value)
    allowed_statuses = {item.value for item in MetricStatus}
    if status not in allowed_statuses:
        raise ValueError("지원하지 않는 metric status입니다.")
    return status


async def _record_scheduler_log(uc_id: str, success: bool, processed_count: int) -> None:
    async with SessionLocal() as session:
        session.add(SchedulerLog(uc_id=uc_id, success=success, processed_count=processed_count))
        await session.commit()


async def collect_metrics() -> None:
    """1분 주기로 서버풀 /metrics를 PULL하고 시계열로 저장한다."""

    processed_count = 0
    success = True
    async with SessionLocal() as session:
        servers = (
            await session.execute(
                select(Server).where(Server.deleted_at.is_(None)).order_by(Server.id)
            )
        ).scalars().all()

        for index, server in enumerate(servers):
            port = settings.serverpool_base_port + index
            url = f"http://{settings.serverpool_host}:{port}/metrics"
            try:
                data = await asyncio.to_thread(_fetch_json, url)
                gpu_usage = data.get("gpuUsage")
                metric = ServerMetric(
                    server_id=server.id,
                    cpu_usage=_usage_value(data, "cpuUsage"),
                    mem_usage=_usage_value(data, "memUsage"),
                    gpu_usage=float(gpu_usage) if gpu_usage is not None else None,
                    net_usage=_usage_value(data, "netUsage"),
                    status=_metric_status(data),
                )
                if metric.gpu_usage is not None and (metric.gpu_usage < 0 or metric.gpu_usage > 100):
                    raise ValueError("gpuUsage는 0부터 100 사이여야 합니다.")
            except (KeyError, TypeError, ValueError, URLError, TimeoutError, OSError):
                success = False
                metric = ServerMetric(
                    server_id=server.id,
                    cpu_usage=0.0,
                    mem_usage=0.0,
                    gpu_usage=None,
                    net_usage=0.0,
                    status=MetricStatus.MISSING.value,
                )
            session.add(metric)
            processed_count += 1

        await session.commit()

    await _record_scheduler_log("UC14", success, processed_count)


async def detect_anomalies() -> None:
    """5분 주기로 CPU 사용률이 μ±2σ를 벗어나는지 기록한다."""

    processed_count = 0
    async with SessionLocal() as session:
        servers = (
            await session.execute(
                select(Server).where(Server.deleted_at.is_(None)).order_by(Server.id)
            )
        ).scalars().all()
        since = _now() - timedelta(hours=1)

        for server in servers:
            latest = await session.scalar(
                select(ServerMetric)
                .where(
                    ServerMetric.server_id == server.id,
                    ServerMetric.status == MetricStatus.OK.value,
                )
                .order_by(ServerMetric.collected_at.desc())
                .limit(1)
            )
            if latest is None:
                continue

            stats = (
                await session.execute(
                    select(
                        func.avg(ServerMetric.cpu_usage),
                        func.stddev_pop(ServerMetric.cpu_usage),
                    ).where(
                        ServerMetric.server_id == server.id,
                        ServerMetric.status == MetricStatus.OK.value,
                        ServerMetric.collected_at >= since,
                        ServerMetric.id != latest.id,
                    )
                )
            ).one()
            mean = float(stats[0] or 0.0)
            stddev = float(stats[1] or 0.0)
            if stddev == 0:
                continue

            if latest.cpu_usage < mean - (2 * stddev) or latest.cpu_usage > mean + (2 * stddev):
                session.add(
                    AnomalyRecord(
                        server_id=server.id,
                        current_value=latest.cpu_usage,
                        mean=mean,
                        stddev=stddev,
                    )
                )
                processed_count += 1

        await session.commit()

    await _record_scheduler_log("UC18", True, processed_count)


def _health_grade(health_score: int) -> str:
    if health_score >= 80:
        return "HEALTHY"
    if health_score >= 50:
        return "WARNING"
    return "CRITICAL"


async def calculate_health_scores() -> None:
    """10분 주기로 최근 메트릭 기반 건강 점수를 계산한다."""

    processed_count = 0
    async with SessionLocal() as session:
        since = _now() - timedelta(minutes=10)
        servers = (
            await session.execute(
                select(Server).where(Server.deleted_at.is_(None)).order_by(Server.id)
            )
        ).scalars().all()
        alert_user_id = await session.scalar(
            select(User.id)
            .where(User.role.in_([UserRole.ADM.value, UserRole.MGR.value]))
            .order_by(User.id)
            .limit(1)
        )

        for server in servers:
            stats = (
                await session.execute(
                    select(
                        func.avg(ServerMetric.cpu_usage),
                        func.avg(ServerMetric.mem_usage),
                        func.avg(ServerMetric.net_usage),
                        func.count(),
                    ).where(
                        ServerMetric.server_id == server.id,
                        ServerMetric.status == MetricStatus.OK.value,
                        ServerMetric.collected_at >= since,
                    )
                )
            ).one()
            if not stats[3]:
                server.health_score = 0
            else:
                cpu = float(stats[0] or 0.0)
                mem = float(stats[1] or 0.0)
                net = float(stats[2] or 0.0)
                load = (cpu * 0.4) + (mem * 0.4) + (net * 0.2)
                server.health_score = max(0, min(100, int(100 - load)))

            grade = _health_grade(server.health_score)
            if grade != "HEALTHY" and alert_user_id is not None:
                session.add(
                    Notification(
                        user_id=alert_user_id,
                        type="HEALTH_GRADE",
                        message=f"{server.name} 건강 등급이 {grade}입니다.",
                        payload={
                            "serverId": server.id,
                            "healthScore": server.health_score,
                            "healthGrade": grade,
                        },
                    )
                )
            processed_count += 1

        session.add(SchedulerLog(uc_id="UC16", success=True, processed_count=processed_count))
        await session.commit()


async def reclaim_idle_servers() -> None:
    """30분 평균 CPU<5% 경고 후 15분 뒤에도 유휴면 예약을 회수한다."""

    processed_count = 0
    current_time = _now()
    async with SessionLocal() as session:
        reservations = (
            await session.execute(
                select(Reservation)
                .where(
                    Reservation.status == ReservationStatus.IN_USE.value,
                    Reservation.start_time <= current_time,
                    Reservation.end_time >= current_time,
                )
                .order_by(Reservation.id)
            )
        ).scalars().all()

        for reservation in reservations:
            average_cpu = await session.scalar(
                select(func.avg(ServerMetric.cpu_usage)).where(
                    ServerMetric.server_id == reservation.server_id,
                    ServerMetric.status == MetricStatus.OK.value,
                    ServerMetric.collected_at >= current_time - timedelta(minutes=30),
                )
            )
            if average_cpu is None or float(average_cpu) >= 5.0:
                continue

            warning = await session.scalar(
                select(Notification)
                .where(
                    Notification.user_id == reservation.user_id,
                    Notification.type == "IDLE_WARNING",
                    Notification.payload["reservationId"].as_integer() == reservation.id,
                )
                .order_by(Notification.created_at.desc())
                .limit(1)
            )
            if warning is None:
                session.add(
                    Notification(
                        user_id=reservation.user_id,
                        type="IDLE_WARNING",
                        message="예약 서버 사용률이 낮아 자동 회수 대상입니다.",
                        payload={
                            "reservationId": reservation.id,
                            "serverId": reservation.server_id,
                        },
                    )
                )
                processed_count += 1
                continue

            if warning.created_at <= current_time - timedelta(minutes=15):
                reservation.status = ReservationStatus.RECLAIMED.value
                server = await session.get(Server, reservation.server_id)
                if server:
                    server.status = ServerStatus.AVAILABLE.value
                    server.version += 1
                session.add(
                    AuditLog(
                        actor_id=reservation.user_id,
                        action=ReservationStatus.RECLAIMED.value,
                        target_type="reservation",
                        target_id=str(reservation.id),
                        detail={"serverId": reservation.server_id},
                    )
                )
                processed_count += 1

        session.add(SchedulerLog(uc_id="UC19", success=True, processed_count=processed_count))
        await session.commit()
