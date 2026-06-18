"""스케줄 잡 단일 등록 지점.

모든 APScheduler 잡을 여기 한 곳에서만 등록한다. 스케줄러 컨테이너(app/scheduler.py)가
이 함수를 호출해 잡을 단독 소유하며, API 프로세스(app/main.py)는 잡을 돌리지 않는다.
잡이 API·스케줄러 양쪽에서 이중 실행되는 것을 막기 위함이다.
"""

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.jobs.anomaly_detection_job import detect_anomalies
from app.jobs.approval_jobs import auto_reject_timed_out_requests
from app.jobs.failure_prediction_job import predict_failures
from app.jobs.forecast_job import generate_forecasts
from app.jobs.health_score_job import compute_health_scores
from app.jobs.idle_reclaim_job import reclaim_idle_servers
from app.jobs.incident_correlation_job import correlate_anomalies
from app.jobs.incident_summary_job import summarize_pending_incidents
from app.jobs.maintenance_transition_job import transition_maintenance_schedules
from app.jobs.metric_collection_job import collect_server_metrics
from app.jobs.reservation_jobs import process_reservation_transitions
from app.jobs.security_monitoring_job import detect_security_threats

# 잡 단일 정의: (id, 콜러블, 데모 주기 초). 등록과 수동 트리거(/admin/run-job)가
# 모두 이 목록 하나만 참조하도록 해 목록 중복을 막는다. 괄호 안은 원래 설계 주기.
_JOB_SPECS: list[tuple[str, Callable[..., Awaitable[None]], int]] = [
    ("reservation_transitions", process_reservation_transitions, 5),   # UC16 (설계 1분)
    ("approval_timeout", auto_reject_timed_out_requests, 5),           # UC17 (설계 1분)
    ("metric_collection", collect_server_metrics, 5),                  # P0 (설계 1분)
    ("anomaly_detection", detect_anomalies, 5),                        # F27 (설계 5분)
    ("health_score", compute_health_scores, 10),                      # F28 (설계 10분)
    ("incident_correlation", correlate_anomalies, 5),                 # F33 (설계 5분)
    ("forecast", generate_forecasts, 30),                            # F31 (설계 60분)
    ("incident_summary", summarize_pending_incidents, 10),           # F34 (설계 5분)
    ("failure_prediction", predict_failures, 15),                    # F32 (설계 10분)
    ("idle_reclaim", reclaim_idle_servers, 5),                       # F24 (설계 1분)
    ("maintenance_transition", transition_maintenance_schedules, 5),  # F30 (설계 1분)
    ("security_monitoring", detect_security_threats, 5),             # F37 (설계 5분)
]

# job_id → 콜러블. 수동 트리거 엔드포인트가 이 매핑으로 잡을 찾는다.
JOB_REGISTRY: dict[str, Callable[..., Awaitable[None]]] = {
    job_id: func for job_id, func, _ in _JOB_SPECS
}


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """모든 주기 잡을 스케줄러에 등록한다. id별 멱등(replace_existing)."""
    for job_id, func, seconds in _JOB_SPECS:
        scheduler.add_job(func, "interval", seconds=seconds,
                          id=job_id, replace_existing=True)
