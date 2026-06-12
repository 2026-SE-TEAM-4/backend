"""운영(ops) API 라우터(UC24·UC22). 잡이 저장한 결과를 읽기 전용으로 조회한다.

무거운 상관·예측 로직은 스케줄러 컨테이너의 잡이 돌고, 여기서는 저장된 결과만 읽는다.
권한은 운영 관리자(MGR/ADM)로 제한한다.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.models import AnomalyRecord, Forecast, Incident, User
from app.schemas.ops import (
    AnomalyResponse,
    ForecastResponse,
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentResponse,
)

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    status: str | None = None,
    severity: str | None = None,
    _user: User = Depends(require_role("MGR", "ADM")),
    db: AsyncSession = Depends(get_db),
) -> IncidentListResponse:
    """인시던트 목록과 노이즈 감소율 조회 [UC24].

    status·severity 로 거를 수 있다. 노이즈 감소율은 전체 이상 대비 인시던트 수로
    계산한다(거름과 무관하게 전체 기준).
    """
    query = select(Incident).order_by(Incident.started_at.desc())
    if status is not None:
        query = query.where(Incident.status == status)
    if severity is not None:
        query = query.where(Incident.severity == severity)
    incidents = (await db.execute(query)).scalars().all()

    noise_reduction_rate = await _noise_reduction_rate(db)
    return IncidentListResponse(
        noise_reduction_rate=noise_reduction_rate,
        incidents=[IncidentResponse.model_validate(incident) for incident in incidents],
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(
    incident_id: int,
    _user: User = Depends(require_role("MGR", "ADM")),
    db: AsyncSession = Depends(get_db),
) -> IncidentDetailResponse:
    """인시던트 상세와 묶인 이상 목록 조회 [UC24]. 없으면 404."""
    incident = await db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "인시던트를 찾을 수 없습니다.")

    anomalies = (
        await db.execute(
            select(AnomalyRecord)
            .where(AnomalyRecord.incident_id == incident_id)
            .order_by(AnomalyRecord.detected_at.desc())
        )
    ).scalars().all()
    return IncidentDetailResponse(
        incident=IncidentResponse.model_validate(incident),
        anomalies=[AnomalyResponse.model_validate(anomaly) for anomaly in anomalies],
    )


@router.get("/forecast", response_model=ForecastResponse)
async def get_forecast(
    metric: str,
    serverId: int | None = None,
    days: int | None = None,
    _user: User = Depends(require_role("MGR", "ADM")),
    db: AsyncSession = Depends(get_db),
) -> ForecastResponse:
    """서버·메트릭별 가장 최근 예측을 조회한다 [UC22]. 없으면 404.

    serverId 가 없으면 풀 전체 예약 수요(RESERVATION_DEMAND) 예측을 가리킨다.
    days 는 정보성 파라미터로, 예측은 잡이 저장한 구간(7일)을 그대로 돌려준다.
    404 는 데이터 부족 등으로 아직 예측이 생성되지 않았음을 뜻한다.
    """
    query = (
        select(Forecast)
        .where(Forecast.metric == metric)
        .order_by(Forecast.generated_at.desc())
        .limit(1)
    )
    # server_id 는 nullable 이라 NULL 비교(is_)와 값 비교를 구분해야 한다.
    if serverId is None:
        query = query.where(Forecast.server_id.is_(None))
    else:
        query = query.where(Forecast.server_id == serverId)

    forecast = await db.scalar(query)
    if forecast is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "예측 결과를 찾을 수 없습니다.")
    return ForecastResponse.model_validate(forecast)


async def _noise_reduction_rate(db: AsyncSession) -> float:
    """전체 이상 대비 묶인 인시던트로 줄인 비율(1 - 인시던트수/이상수). 이상 없으면 0."""
    total_anomalies = await db.scalar(select(func.count()).select_from(AnomalyRecord)) or 0
    if total_anomalies == 0:
        return 0.0
    total_incidents = await db.scalar(select(func.count()).select_from(Incident)) or 0
    # 인시던트 수가 이상 수보다 많으면(아직 이상이 부착되지 않은 인시던트 등) 값이
    # 음수가 될 수 있다. 감소율은 0 미만이 의미 없으므로 0 으로 바닥을 둔다.
    return max(0.0, 1 - (total_incidents / total_anomalies))
