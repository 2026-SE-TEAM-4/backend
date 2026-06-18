"""관리자 고급 기능 라우터.

데모·실 테스트를 위한 운영 데이터 초기화 엔드포인트를 제공한다.
모든 엔드포인트는 ADM 전용이다.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.database import SessionLocal
from app.jobs.scheduling import JOB_REGISTRY
from app.models import Server, ServerMetric, User
from app.models.enums import IncidentSeverity, SecurityEventType
from app.schemas.admin import ResetResult, RunJobResult, SeedAnomalyResult
from app.services import admin as admin_service
from app.services.security_event_service import record_event

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset/availability", response_model=ResetResult)
async def reset_availability(
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """가용성 히스토리 초기화 [고급].

    ServerMetric과 ServerHealthHistory를 전부 삭제한다.
    이후 스케줄러가 다시 수집하면 히스토리가 새로 쌓인다.
    """
    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.WARNING.value,
        actor_id=actor.id,
        target_type="system",
        detail={"action": "reset_availability"},
    )
    return await admin_service.reset_availability(db)


@router.post("/reset/aiops", response_model=ResetResult)
async def reset_aiops(
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """AIOps 데이터 초기화 [고급].

    Incident, AnomalyRecord, IncidentSummary, Forecast, SchedulerLog를 삭제한다.
    """
    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.WARNING.value,
        actor_id=actor.id,
        target_type="system",
        detail={"action": "reset_aiops"},
    )
    return await admin_service.reset_aiops(db)


@router.post("/reset/notifications", response_model=ResetResult)
async def reset_notifications(
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """알림·감사 로그 초기화 [고급].

    Notification과 AuditLog를 삭제한다.
    """
    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.WARNING.value,
        actor_id=actor.id,
        target_type="system",
        detail={"action": "reset_notifications"},
    )
    return await admin_service.reset_notifications(db)


@router.post("/reset/reservations", response_model=ResetResult)
async def reset_reservations(
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """예약·승인·대기열 초기화 [고급].

    Reservation, ApprovalRequest, QueueEntry, MaintenanceSchedule을 삭제한다.
    """
    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.WARNING.value,
        actor_id=actor.id,
        target_type="system",
        detail={"action": "reset_reservations"},
    )
    return await admin_service.reset_reservations(db)


@router.post("/reset/all", response_model=ResetResult)
async def reset_all(
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """전체 운영 데이터 초기화 [고급].

    마스터 데이터(User, Team, Quota, Server)를 제외한 모든 운영 데이터를 삭제한다.
    데모 초기 상태로 되돌릴 때 사용한다.
    """
    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.CRITICAL.value,
        actor_id=actor.id,
        target_type="system",
        detail={"action": "reset_all"},
    )
    return await admin_service.reset_all(db)


@router.post("/reset/security", response_model=ResetResult)
async def reset_security(
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> ResetResult:
    """보안 데이터 초기화 [고급].

    SecurityEvent와 SecurityAlert를 전부 삭제한다.
    """
    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.WARNING.value,
        actor_id=actor.id,
        target_type="system",
        detail={"action": "reset_security"},
    )
    return await admin_service.reset_security(db)


@router.post("/run-job/{job_id}", response_model=RunJobResult)
async def run_job(
    job_id: str,
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> RunJobResult:
    """스케줄 잡 수동 실행 [고급].

    데모·테스트에서 스케줄 주기를 기다리지 않고 잡을 즉시 한 번 돌린다.
    job_id 는 scheduling.py 의 JOB_REGISTRY 단일 출처에서 찾는다(목록 중복 없음).
    잡은 자체 세션 팩토리로 동작하므로 SessionLocal 을 그대로 넘긴다.
    """
    job = JOB_REGISTRY.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"알 수 없는 잡: {job_id}")

    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.WARNING.value,
        actor_id=actor.id,
        target_type="system",
        detail={"action": "run_job", "jobId": job_id},
    )
    await db.commit()

    ran_at = datetime.now(tz=timezone.utc)
    await job(session_factory=SessionLocal)
    return RunJobResult(job_id=job_id, ran_at=ran_at, ok=True)


# 이상탐지 잡이 이상으로 판정할 만큼의 안정 기준선 + 명백한 스파이크 표본 수.
# anomaly_detection_job: 최소 표본(MIN_SAMPLES=30) + 연속분(2) 이상 필요하므로
# 넉넉히 60개의 안정 표본 뒤 마지막에 한 개의 스파이크를 둔다.
_ANOMALY_BASELINE_SAMPLES = 60
_ANOMALY_BASELINE_CPU = 50.0
_ANOMALY_SPIKE_CPU = 99.0


@router.post("/seed-anomaly/{server_id}", response_model=SeedAnomalyResult)
async def seed_anomaly(
    server_id: int,
    actor: User = Depends(require_role("ADM")),
    db: AsyncSession = Depends(get_db),
) -> SeedAnomalyResult:
    """이상탐지 시연용 메트릭 주입 [고급].

    라이브 데모에서 AIOps 파이프라인이 곧바로 이상을 잡도록, 대상 서버에
    과거 시각의 안정 기준선 표본 여러 개와 명백한 스파이크 한 개를 적재한다.
    다음 anomaly_detection 잡 실행이 이 서버의 CPU 이상을 기록하게 된다.
    (test_aiops_jobs.py 의 '백데이트 메트릭 적재 후 잡 호출' 패턴을 따른다.)
    """
    server = await db.get(Server, server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"서버를 찾을 수 없습니다: {server_id}")

    record_event(
        db,
        event_type=SecurityEventType.ADMIN_ACTION.value,
        severity=IncidentSeverity.WARNING.value,
        actor_id=actor.id,
        target_type="server",
        target_id=str(server_id),
        detail={"action": "seed_anomaly"},
    )

    # 백데이트한 안정 구간(σ>0 이 되도록 ±1 진동) 뒤 마지막에 스파이크 한 개.
    base = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    for i in range(_ANOMALY_BASELINE_SAMPLES):
        db.add(ServerMetric(
            server_id=server_id,
            cpu_usage=_ANOMALY_BASELINE_CPU + (1 if i % 2 else -1),
            mem_usage=40.0, net_usage=5.0, gpu_usage=None, status="OK",
            collected_at=base + timedelta(minutes=i),
        ))
    db.add(ServerMetric(
        server_id=server_id,
        cpu_usage=_ANOMALY_SPIKE_CPU,
        mem_usage=40.0, net_usage=5.0, gpu_usage=None, status="OK",
        collected_at=base + timedelta(minutes=_ANOMALY_BASELINE_SAMPLES),
    ))
    await db.commit()

    inserted = _ANOMALY_BASELINE_SAMPLES + 1
    return SeedAnomalyResult(
        server_id=server_id,
        inserted=inserted,
        message=f"서버 {server_id} 에 안정 표본 {_ANOMALY_BASELINE_SAMPLES}개 + 스파이크 1개 적재 완료",
    )
