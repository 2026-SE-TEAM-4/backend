"""스케줄 잡 단일 등록 지점.

모든 APScheduler 잡을 여기 한 곳에서만 등록한다. 스케줄러 컨테이너(app/scheduler.py)가
이 함수를 호출해 잡을 단독 소유하며, API 프로세스(app/main.py)는 잡을 돌리지 않는다.
잡이 API·스케줄러 양쪽에서 이중 실행되는 것을 막기 위함이다.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.jobs.anomaly_detection_job import detect_anomalies
from app.jobs.approval_jobs import auto_reject_timed_out_requests
from app.jobs.forecast_job import generate_forecasts
from app.jobs.health_score_job import compute_health_scores
from app.jobs.incident_correlation_job import correlate_anomalies
from app.jobs.incident_summary_job import summarize_pending_incidents
from app.jobs.metric_collection_job import collect_server_metrics
from app.jobs.reservation_jobs import process_reservation_transitions


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """모든 주기 잡을 스케줄러에 등록한다. id별 멱등(replace_existing)."""
    # UC16: 예약 만료·사용 시작 자동 전이
    scheduler.add_job(process_reservation_transitions, "interval", minutes=1,
                      id="reservation_transitions", replace_existing=True)
    # UC17: 72시간 초과 PENDING 승인 요청 자동 거절
    scheduler.add_job(auto_reject_timed_out_requests, "interval", minutes=1,
                      id="approval_timeout", replace_existing=True)
    # P0: 서버풀 메트릭 수집
    scheduler.add_job(collect_server_metrics, "interval", minutes=1,
                      id="metric_collection", replace_existing=True)
    # F27: 이상탐지
    scheduler.add_job(detect_anomalies, "interval", minutes=5,
                      id="anomaly_detection", replace_existing=True)
    # F28: 건강점수 산출
    scheduler.add_job(compute_health_scores, "interval", minutes=10,
                      id="health_score", replace_existing=True)
    # F33: 인시던트 상관(이상 묶기·노이즈 감소)
    scheduler.add_job(correlate_anomalies, "interval", minutes=5,
                      id="incident_correlation", replace_existing=True)
    # F31: 용량·수요 예측(Holt-Winters, 7일)
    scheduler.add_job(generate_forecasts, "interval", minutes=60,
                      id="forecast", replace_existing=True)
    # F34: LLM 원인 요약(OPEN 인시던트당 1회, 키 없으면 잡 내부에서 건너뜀)
    scheduler.add_job(summarize_pending_incidents, "interval", minutes=5,
                      id="incident_summary", replace_existing=True)
