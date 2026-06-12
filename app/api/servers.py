"""서버 도메인 API 라우터.

두 갈래를 한 라우터로 묶는다.
- 서버 관리 CRUD·조회(F01·F02·F08·F14·F15·F16): 목록/상세/대안/등록/삭제/점검등록.
- 건강·위험 추세(UC23): 장애 예측 잡이 저장한 결과를 읽기 전용으로 조회.

인증은 시스템 공통 JWT 의존성(app/core/deps)을 쓴다. 조회는 로그인 사용자면 되고,
생성·삭제·점검 등록은 서버 관리자(ADM)로 제한한다.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.core.exceptions import ConflictError, NotFoundError
from app.models import AnomalyRecord, Server, ServerHealthHistory, User
from app.schemas.ops import HealthTrendPoint, HealthTrendResponse
from app.schemas.servers import (
    MaintenanceCreate,
    MaintenanceCreateResponse,
    ServerAlternativeResponse,
    ServerCreate,
    ServerCreateResponse,
    ServerDeleteResponse,
    ServerDetailResponse,
    ServerListResponse,
    ServerSort,
)
from app.services import servers as server_service
from app.services.failure_prediction import classify_trend, ewma_slope, risk_drivers

router = APIRouter(prefix="/servers", tags=["servers"])

# 추세·이력을 보는 과거 구간과 이상 빈도 윈도우(잡과 같은 기준).
_HISTORY_WINDOW = timedelta(days=7)
_ANOMALY_WINDOW = timedelta(hours=24)


def _raise_api_error(error: Exception) -> None:
    """서비스 예외를 HTTP 상태로 바꾼다."""
    if isinstance(error, NotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    if isinstance(error, ConflictError):
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    raise error


@router.post("", response_model=ServerCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    data: ServerCreate,
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ServerCreateResponse:
    """서버 등록 [UC11]. 이름·IP 중복 시 409."""
    try:
        return await server_service.create_server(db, data)
    except ConflictError as error:
        _raise_api_error(error)
        raise


@router.get("", response_model=ServerListResponse)
async def list_servers(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status_value: Annotated[str | None, Query(alias="status")] = None,
    group_name: Annotated[str | None, Query(alias="group")] = None,
    sort: Annotated[ServerSort, Query()] = "id",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ServerListResponse:
    """서버 현황 조회 [UC01]. 상태·그룹 필터, 정렬, 페이지네이션.

    공유 풀이라 모든 로그인 사용자가 전체 서버를 본다. 점유자(occupant)는 권한에 따라
    실명(ADM/MGR) 또는 팀 코드(STU)로 노출한다.
    """
    return await server_service.list_servers(
        session=db,
        status=status_value,
        group_name=group_name,
        user_role=_user.role,
        scope_group_name=None,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/alternatives", response_model=ServerAlternativeResponse)
async def list_alternatives(
    server_id: Annotated[int, Query(alias="serverId")],
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ServerAlternativeResponse:
    """대안 서버 조회 [UC03-d]. 유사 사양 AVAILABLE 서버 최대 5건."""
    try:
        return await server_service.list_alternative_servers(db, server_id)
    except NotFoundError as error:
        _raise_api_error(error)
        raise


@router.get("/{server_id}", response_model=ServerDetailResponse)
async def get_server(
    server_id: int,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ServerDetailResponse:
    """서버 상세 조회 [UC01]. 없으면 404."""
    try:
        return await server_service.get_server(db, server_id)
    except NotFoundError as error:
        _raise_api_error(error)
        raise


@router.get("/{server_id}/health-trend", response_model=HealthTrendResponse)
async def get_health_trend(
    server_id: int,
    _user: User = Depends(require_role("MGR", "ADM")),
    db: AsyncSession = Depends(get_db),
) -> HealthTrendResponse:
    """서버의 건강·위험 추세 조회 [UC23]. 없는 서버는 404.

    잡이 저장한 risk_score·eta_to_risk 와 최근 7일 건강점수 이력을 돌려준다. trend 는
    이력 기울기로 다시 계산하고, drivers 는 기울기·이상빈도·현재건강으로 근거를 만든다.
    """
    server = await db.get(Server, server_id)
    if server is None or server.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "서버를 찾을 수 없습니다.")

    now = datetime.now(tz=timezone.utc)
    history_rows = await _health_history(db, server_id, now)
    slope = ewma_slope([(ts, float(score)) for ts, score in history_rows])
    anomaly_count = await _anomaly_count_24h(db, server_id, now)

    drivers = risk_drivers(
        health_slope=slope,
        anomaly_count_24h=anomaly_count,
        current_health=server.health_score,
    )
    return HealthTrendResponse(
        server_id=server.id,
        health_score=server.health_score,
        risk_score=server.risk_score,
        trend=classify_trend(slope),
        eta_to_risk=server.eta_to_risk,
        history=[HealthTrendPoint(ts=ts, health_score=score) for ts, score in history_rows],
        drivers=drivers,
    )


@router.delete("/{server_id}", response_model=ServerDeleteResponse)
async def delete_server(
    server_id: int,
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ServerDeleteResponse:
    """서버 삭제 [UC12]. soft delete. 활성 예약이 있으면 409."""
    try:
        return await server_service.soft_delete_server(db, server_id)
    except (ConflictError, NotFoundError) as error:
        _raise_api_error(error)
        raise


@router.post(
    "/{server_id}/maintenances",
    response_model=MaintenanceCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_maintenance(
    server_id: int,
    data: MaintenanceCreate,
    user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceCreateResponse:
    """점검 스케줄 등록 [UC13]. 예약과 겹치면 409(force=true 면 강행)."""
    try:
        return await server_service.create_maintenance(db, server_id, data, user.id)
    except (ConflictError, NotFoundError) as error:
        _raise_api_error(error)
        raise


async def _health_history(
    db: AsyncSession, server_id: int, now: datetime
) -> list[tuple[datetime, int]]:
    """최근 7일 건강점수 이력을 (시각, 점수) 시간순 목록으로 읽는다."""
    rows = (
        await db.execute(
            select(ServerHealthHistory.recorded_at, ServerHealthHistory.score)
            .where(
                ServerHealthHistory.server_id == server_id,
                ServerHealthHistory.recorded_at >= now - _HISTORY_WINDOW,
            )
            .order_by(ServerHealthHistory.recorded_at)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def _anomaly_count_24h(db: AsyncSession, server_id: int, now: datetime) -> int:
    """최근 24h 동안 이 서버에 기록된 이상 건수를 센다(근거 문구용)."""
    count = await db.scalar(
        select(func.count())
        .select_from(AnomalyRecord)
        .where(
            AnomalyRecord.server_id == server_id,
            AnomalyRecord.detected_at >= now - _ANOMALY_WINDOW,
        )
    )
    return count or 0
