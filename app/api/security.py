"""보안 관제 API 라우터(UC26·UC27·UC28, F38). 전부 ADM 전용."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.models import SecurityAlert, SecurityEvent, User
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    SecurityAlertType,
    SecurityEventType,
)
from app.schemas.security import (
    SecurityAlertResponse,
    SecurityEventResponse,
    SecuritySummaryResponse,
    SimulateRequest,
    SimulateResponse,
)

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/events", response_model=list[SecurityEventResponse])
async def list_security_events(
    eventType: str | None = None,
    severity: str | None = None,
    # from_/to_ 는 Python 예약어와 충돌하므로 쿼리 파라미터명과 내부 변수명을 분리한다.
    # FastAPI Query 는 파라미터 이름 그대로 URL 쿼리 키로 쓰기 때문에 alias 를 쓴다.
    from_: str | None = None,
    to_: str | None = None,
    limit: int = 100,
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> list[SecurityEventResponse]:
    """보안 이벤트 목록 조회 [UC28]. occurred_at 내림차순."""
    query = select(SecurityEvent).order_by(SecurityEvent.occurred_at.desc()).limit(limit)
    if eventType is not None:
        query = query.where(SecurityEvent.event_type == eventType)
    if severity is not None:
        query = query.where(SecurityEvent.severity == severity)
    if from_ is not None:
        query = query.where(SecurityEvent.occurred_at >= datetime.fromisoformat(from_))
    if to_ is not None:
        query = query.where(SecurityEvent.occurred_at <= datetime.fromisoformat(to_))

    events = (await db.execute(query)).scalars().all()
    return [SecurityEventResponse.model_validate(e) for e in events]


@router.get("/alerts", response_model=list[SecurityAlertResponse])
async def list_security_alerts(
    status: str | None = None,
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> list[SecurityAlertResponse]:
    """보안 경보 목록 조회 [UC28]. started_at 내림차순."""
    query = select(SecurityAlert).order_by(SecurityAlert.started_at.desc())
    if status is not None:
        query = query.where(SecurityAlert.status == status)

    alerts = (await db.execute(query)).scalars().all()
    return [SecurityAlertResponse.model_validate(a) for a in alerts]


@router.get("/summary", response_model=SecuritySummaryResponse)
async def get_security_summary(
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> SecuritySummaryResponse:
    """보안 KPI 집계 [UC28]. 대시보드 타일용."""
    today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    today_events = await db.scalar(
        select(func.count()).select_from(SecurityEvent).where(
            SecurityEvent.occurred_at >= today_start
        )
    ) or 0

    open_alerts = await db.scalar(
        select(func.count()).select_from(SecurityAlert).where(
            SecurityAlert.status == IncidentStatus.OPEN.value
        )
    ) or 0

    critical_alerts = await db.scalar(
        select(func.count()).select_from(SecurityAlert).where(
            SecurityAlert.status == IncidentStatus.OPEN.value,
            SecurityAlert.severity == IncidentSeverity.CRITICAL.value,
        )
    ) or 0

    brute_force_suspects = await db.scalar(
        select(func.count()).select_from(SecurityAlert).where(
            SecurityAlert.alert_type == SecurityAlertType.BRUTE_FORCE.value,
            SecurityAlert.status == IncidentStatus.OPEN.value,
        )
    ) or 0

    return SecuritySummaryResponse(
        today_events=today_events,
        open_alerts=open_alerts,
        critical_alerts=critical_alerts,
        brute_force_suspects=brute_force_suspects,
    )


@router.patch("/alerts/{alert_id}/resolve", response_model=SecurityAlertResponse)
async def resolve_security_alert(
    alert_id: int,
    resolver: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> SecurityAlertResponse:
    """보안 경보 수동 해결 [UC28]. 없으면 404, 이미 해결이면 멱등 반환."""
    alert = await db.get(SecurityAlert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "보안 경보를 찾을 수 없습니다.")

    if alert.status != IncidentStatus.RESOLVED.value:
        alert.status = IncidentStatus.RESOLVED.value
        alert.resolved_at = datetime.now(tz=timezone.utc)
        alert.resolved_by = resolver.id
        await db.commit()
        await db.refresh(alert)

    return SecurityAlertResponse.model_validate(alert)


@router.post("/simulate", response_model=SimulateResponse)
async def simulate_security_scenario(
    body: SimulateRequest,
    _user: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> SimulateResponse:
    """보안 시뮬레이션 [UC28]. 임계를 넘기는 가짜 SecurityEvent 를 삽입한다.

    삽입 후 탐지 잡이 실행되면 해당 경보가 생성된다. 데모용이다.
    """
    if body.scenario not in ("brute_force", "access_abuse", "agent_down", "admin_abuse"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "scenario 는 brute_force | access_abuse | agent_down | admin_abuse 중 하나여야 합니다.",
        )

    inserted = await _insert_simulation_events(db, body.scenario)
    await db.commit()
    return SimulateResponse(inserted=inserted, scenario=body.scenario)


async def _insert_simulation_events(db: AsyncSession, scenario: str) -> int:
    """시나리오에 맞는 가짜 이벤트를 임계 이상으로 삽입한다."""
    now = datetime.now(tz=timezone.utc)

    if scenario == "brute_force":
        # 같은 IP 에서 6회 로그인 실패(임계 5)
        for i in range(6):
            db.add(SecurityEvent(
                event_type=SecurityEventType.LOGIN_FAILURE.value,
                severity=IncidentSeverity.INFO.value,
                source_ip="192.168.1.100",
                identifier=f"attacker{i}@example.com",
            ))
        return 6

    if scenario == "access_abuse":
        # actor_id=1 이 6회 권한 거부(임계 5)
        for _ in range(6):
            db.add(SecurityEvent(
                event_type=SecurityEventType.ACCESS_DENIED.value,
                severity=IncidentSeverity.WARNING.value,
                actor_id=1,
                source_ip="10.0.0.1",
                detail={"path": "/admin/reset/all"},
            ))
        return 6

    if scenario == "agent_down":
        # 서버 1이 4회 응답 없음(임계 3)
        for _ in range(4):
            db.add(SecurityEvent(
                event_type=SecurityEventType.AGENT_UNREACHABLE.value,
                severity=IncidentSeverity.WARNING.value,
                target_type="server",
                target_id="1",
            ))
        return 4

    # admin_abuse
    # actor_id=1 이 6회 민감 작업(임계 5)
    for _ in range(6):
        db.add(SecurityEvent(
            event_type=SecurityEventType.ADMIN_ACTION.value,
            severity=IncidentSeverity.WARNING.value,
            actor_id=1,
            target_type="system",
            detail={"action": "simulate_admin_abuse"},
        ))
    return 6
