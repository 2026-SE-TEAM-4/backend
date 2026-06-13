"""스케줄 잡 단일 등록 지점.

모든 APScheduler 잡을 여기 한 곳에서만 등록한다. 스케줄러 컨테이너(app/scheduler.py)가
이 함수를 호출해 잡을 단독 소유하며, API 프로세스(app/main.py)는 잡을 돌리지 않는다.
잡이 API·스케줄러 양쪽에서 이중 실행되는 것을 막기 위함이다.
"""

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


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """모든 주기 잡을 스케줄러에 등록한다. id별 멱등(replace_existing)."""
    # UC16: 예약 만료·사용 시작 자동 전이
    scheduler.add_job(process_reservation_transitions, "interval", seconds=5,
                      id="reservation_transitions", replace_existing=True)
    # UC17: 72시간 초과 PENDING 승인 요청 자동 거절
    scheduler.add_job(auto_reject_timed_out_requests, "interval", seconds=5,
                      id="approval_timeout", replace_existing=True)
    # P0: 서버풀 메트릭 수집
    scheduler.add_job(collect_server_metrics, "interval", seconds=5,
                      id="metric_collection", replace_existing=True)
    # F27: 이상탐지
    scheduler.add_job(detect_anomalies, "interval", seconds=5,
                      id="anomaly_detection", replace_existing=True)
    # F28: 건강점수 산출
    scheduler.add_job(compute_health_scores, "interval", seconds=10,
                      id="health_score", replace_existing=True)
    # F33: 인시던트 상관(이상 묶기·노이즈 감소)
    scheduler.add_job(correlate_anomalies, "interval", seconds=5,
                      id="incident_correlation", replace_existing=True)
    # F31: 용량·수요 예측(Holt-Winters, 7일 데이터 연산 비용 고려)
    scheduler.add_job(generate_forecasts, "interval", seconds=30,
                      id="forecast", replace_existing=True)
    # F34: LLM 원인 요약(OPEN 인시던트당 1회, 키 없으면 잡 내부에서 건너뜀)
    scheduler.add_job(summarize_pending_incidents, "interval", seconds=10,
                      id="incident_summary", replace_existing=True)
    # F32: 장애·건강 열화 예측(7일 추세 + 위험도, F28 직후)
    scheduler.add_job(predict_failures, "interval", seconds=15,
                      id="failure_prediction", replace_existing=True)
    # F24: 유휴 서버 감지·자동 회수(경고 후 회수)
    scheduler.add_job(reclaim_idle_servers, "interval", seconds=5,
                      id="idle_reclaim", replace_existing=True)
    # F30: 점검 스케줄 자동 상태 전환(MAINTENANCE/AVAILABLE)
    scheduler.add_job(transition_maintenance_schedules, "interval", seconds=5,
                      id="maintenance_transition", replace_existing=True)
