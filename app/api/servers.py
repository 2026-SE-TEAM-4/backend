"""서버 도메인 API 라우터(UC23). 장애 예측 잡이 저장한 위험·이력을 읽기 전용으로 조회한다.

무거운 추세·위험 산출은 스케줄러 컨테이너의 잡이 돌고, 여기서는 저장된 결과만 읽는다.
추세(trend)는 저장된 이력의 기울기로 다시 계산해 노출한다. 권한은 운영 관리자(MGR/ADM)로
제한한다(ops.py 와 동일 패턴).
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.models import AnomalyRecord, Server, ServerHealthHistory, User
from app.schemas.ops import HealthTrendPoint, HealthTrendResponse
from app.services.failure_prediction import classify_trend, ewma_slope, risk_drivers

router = APIRouter(prefix="/servers", tags=["servers"])

# 추세·이력을 보는 과거 구간과 이상 빈도 윈도우(잡과 같은 기준).
_HISTORY_WINDOW = timedelta(days=7)
_ANOMALY_WINDOW = timedelta(hours=24)


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
    if server is None:
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
