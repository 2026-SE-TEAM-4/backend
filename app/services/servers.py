"""서버 관리 비즈니스 로직."""

from datetime import datetime, timezone

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import MaintenanceSchedule, Reservation, Server, ServerMetric, Team, User
from app.models.enums import ReservationStatus, ServerStatus
from app.schemas.servers import (
    AlternativeSpec,
    LatestMetric,
    MaintenanceCreate,
    MaintenanceCreateResponse,
    ServerAlternative,
    ServerAlternativeResponse,
    ServerCreate,
    ServerCreateResponse,
    ServerDeleteResponse,
    ServerDetailResponse,
    ServerListItem,
    ServerListResponse,
    ServerSpec,
)

ACTIVE_RESERVATION_STATUSES = [
    ReservationStatus.RESERVED.value,
    ReservationStatus.IN_USE.value,
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _server_spec(server: Server) -> ServerSpec:
    return ServerSpec(
        cpu_cores=server.cpu_cores,
        ram_gb=server.ram_gb,
        gpu_model=server.gpu_model,
    )


def _server_detail(server: Server) -> ServerDetailResponse:
    return ServerDetailResponse(
        id=server.id,
        name=server.name,
        status=server.status,
        spec=_server_spec(server),
        health_score=server.health_score,
        ip=server.ip,
        group_name=server.group_name,
        risk_score=server.risk_score,
        eta_to_risk=server.eta_to_risk,
    )


def _to_latest_metric(raw_metric: ServerMetric | None) -> LatestMetric | None:
    if raw_metric is None:
        return None
    return LatestMetric(
        cpu_usage=raw_metric.cpu_usage,
        mem_usage=raw_metric.mem_usage,
        net_usage=raw_metric.net_usage,
        gpu_usage=raw_metric.gpu_usage,
        status=raw_metric.status,
        collected_at=raw_metric.collected_at,
    )


async def _latest_metric_for(session: AsyncSession, server_id: int) -> LatestMetric | None:
    """서버 한 대의 최신 메트릭을 단건 조회한다."""
    raw_metric = await session.scalar(
        select(ServerMetric)
        .where(ServerMetric.server_id == server_id)
        .order_by(ServerMetric.collected_at.desc())
        .limit(1)
    )
    return _to_latest_metric(raw_metric)


async def _occupant_label(
    session: AsyncSession,
    server_id: int,
    user_role: str,
    current_time: datetime,
) -> str | None:
    """현재 점유 중인 사용자 라벨. ADM/MGR 은 실명, 그 외는 팀 코드."""
    occupant = (
        await session.execute(
            select(User, Team)
            .select_from(Reservation)
            .join(User, User.id == Reservation.user_id)
            .join(Team, Team.id == User.team_id)
            .where(
                Reservation.server_id == server_id,
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
                Reservation.start_time <= current_time,
                Reservation.end_time >= current_time,
            )
            .order_by(Reservation.end_time.asc())
            .limit(1)
        )
    ).first()
    if occupant is None:
        return None
    user, team = occupant
    if user and team:
        return user.name if user_role in ["ADM", "MGR"] else team.code
    return None


async def create_server(session: AsyncSession, data: ServerCreate) -> ServerCreateResponse:
    duplicated_server = await session.scalar(
        select(Server.id)
        .where(
            Server.deleted_at.is_(None),
            (Server.ip == data.ip) | (Server.name == data.name),
        )
        .limit(1)
    )
    if duplicated_server is not None:
        raise ConflictError("이미 등록된 서버 이름 또는 IP입니다.")

    server = Server(
        name=data.name,
        ip=data.ip,
        cpu_cores=data.cpu_cores,
        ram_gb=data.ram_gb,
        gpu_model=data.gpu_model,
        group_name=data.group_name,
        status=ServerStatus.MAINTENANCE.value if data.start_in_maintenance else ServerStatus.AVAILABLE.value,
        version=1,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return ServerCreateResponse(id=server.id, status=server.status, version=server.version)


async def get_server(
    session: AsyncSession, server_id: int, user_role: str
) -> ServerDetailResponse:
    server = await session.get(Server, server_id)
    if server is None or server.deleted_at is not None:
        raise NotFoundError("서버를 찾을 수 없습니다.")

    detail = _server_detail(server)
    detail.occupant = await _occupant_label(session, server.id, user_role, _now())
    detail.latest_metric = await _latest_metric_for(session, server.id)
    return detail


async def list_servers(
    session: AsyncSession,
    status: str | None,
    group_name: str | None,
    user_role: str,
    scope_group_name: str | None,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> ServerListResponse:
    conditions = [Server.deleted_at.is_(None)]
    if status:
        conditions.append(Server.status == status)
    if group_name:
        conditions.append(Server.group_name == group_name)
    if user_role != "ADM" and scope_group_name:
        conditions.append(Server.group_name == scope_group_name)

    sort_column = getattr(Server, sort)
    if order == "desc":
        sort_column = sort_column.desc()

    servers = (
        await session.execute(
            select(Server).where(*conditions).order_by(sort_column).limit(limit).offset(offset)
        )
    ).scalars().all()

    server_ids = [s.id for s in servers]

    # 서버별 최신 메트릭을 한 번의 쿼리로 조회 (서버당 N+1 방지)
    latest_metric_map: dict[int, ServerMetric] = {}
    if server_ids:
        max_at_subq = (
            select(
                ServerMetric.server_id,
                func.max(ServerMetric.collected_at).label("max_at"),
            )
            .where(ServerMetric.server_id.in_(server_ids))
            .group_by(ServerMetric.server_id)
            .subquery()
        )
        metric_rows = (
            await session.execute(
                select(ServerMetric).join(
                    max_at_subq,
                    and_(
                        ServerMetric.server_id == max_at_subq.c.server_id,
                        ServerMetric.collected_at == max_at_subq.c.max_at,
                    ),
                )
            )
        ).scalars().all()
        for m in metric_rows:
            latest_metric_map[m.server_id] = m

    items: list[ServerListItem] = []
    current_time = _now()
    for server in servers:
        occupant_value = await _occupant_label(session, server.id, user_role, current_time)
        latest_metric = _to_latest_metric(latest_metric_map.get(server.id))

        item = ServerListItem.model_validate(_server_detail(server).model_dump())
        item.occupant = occupant_value
        item.latest_metric = latest_metric
        items.append(item)

    return ServerListResponse(servers=items)


async def soft_delete_server(session: AsyncSession, server_id: int) -> ServerDeleteResponse:
    server = await session.get(Server, server_id)
    if server is None or server.deleted_at is not None:
        raise NotFoundError("서버를 찾을 수 없습니다.")

    active_count = await session.scalar(
        select(func.count())
        .select_from(Reservation)
        .where(
            Reservation.server_id == server_id,
            Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
        )
    )
    if active_count:
        raise ConflictError("활성 예약이 있어 서버를 삭제할 수 없습니다.")

    server.deleted_at = _now()
    server.version += 1
    await session.commit()
    await session.refresh(server)
    return ServerDeleteResponse(id=server.id, deleted_at=server.deleted_at)


def _reservation_overlap(start_time: datetime, end_time: datetime):
    return and_(Reservation.start_time < end_time, Reservation.end_time > start_time)


async def list_alternative_servers(
    session: AsyncSession,
    server_id: int,
) -> ServerAlternativeResponse:
    source = await session.get(Server, server_id)
    if source is None or source.deleted_at is not None:
        raise NotFoundError("서버를 찾을 수 없습니다.")

    conditions = [
        Server.deleted_at.is_(None),
        Server.id != server_id,
        Server.status == ServerStatus.AVAILABLE.value,
        Server.cpu_cores >= source.cpu_cores,
        Server.ram_gb >= source.ram_gb,
    ]
    if source.gpu_model:
        conditions.append(Server.gpu_model == source.gpu_model)

    servers = (await session.execute(select(Server).where(*conditions))).scalars().all()

    alternatives: list[ServerAlternative] = []
    for server in servers:
        alternatives.append(
            ServerAlternative(
                id=server.id,
                name=server.name,
                spec=AlternativeSpec(cpu_cores=server.cpu_cores, ram_gb=server.ram_gb),
            )
        )

    alternatives.sort(
        key=lambda item: (
            abs(item.spec.cpu_cores - source.cpu_cores) + abs(item.spec.ram_gb - source.ram_gb),
            item.id,
        )
    )
    return ServerAlternativeResponse(alternatives=alternatives[:5])


async def create_maintenance(
    session: AsyncSession,
    server_id: int,
    data: MaintenanceCreate,
    created_by: int,
) -> MaintenanceCreateResponse:
    server = await session.get(Server, server_id)
    if server is None or server.deleted_at is not None:
        raise NotFoundError("서버를 찾을 수 없습니다.")

    if not data.force:
        conflict = await session.scalar(
            select(Reservation.id)
            .where(
                Reservation.server_id == server_id,
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
                _reservation_overlap(data.start_at, data.end_at),
            )
            .limit(1)
        )
        if conflict is not None:
            raise ConflictError("점검 시간과 겹치는 예약이 있습니다.")

    maintenance = MaintenanceSchedule(
        server_id=server_id,
        start_at=data.start_at,
        end_at=data.end_at,
        reason=data.reason,
        recurring_rule=data.recurring_rule,
        created_by=created_by,
    )
    session.add(maintenance)
    await session.execute(
        update(Server)
        .where(Server.id == server_id)
        .values(version=Server.version + 1)
    )
    await session.commit()
    await session.refresh(maintenance)
    return MaintenanceCreateResponse(maintenance_id=maintenance.id)
