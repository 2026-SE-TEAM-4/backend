"""스케줄러 잡 등록 단위 테스트.

잡 이중 실행 방지를 위해 모든 스케줄 잡은 한 곳(register_jobs)에서만 등록한다.
스케줄러 컨테이너(app/scheduler.py)가 이 함수를 호출해 잡을 단독 소유한다.
"""

from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.jobs.scheduling import register_jobs


def _intervals_by_id(scheduler: AsyncIOScheduler) -> dict[str, timedelta]:
    return {job.id: job.trigger.interval for job in scheduler.get_jobs()}


def test_register_jobs_registers_all_expected_jobs():
    scheduler = AsyncIOScheduler()
    register_jobs(scheduler)

    # 로컬 데모용 가속 간격(초 단위). 노트북에서 2~4시간 돌려도 결과가 빨리 보이도록
    # 설계상의 분 단위 대신 초 단위로 등록한다. 등록 위치는 scheduling.py 가 단일 출처다.
    intervals = _intervals_by_id(scheduler)
    assert intervals == {
        "reservation_transitions": timedelta(seconds=5),
        "approval_timeout": timedelta(seconds=5),
        "metric_collection": timedelta(seconds=5),
        "anomaly_detection": timedelta(seconds=5),
        "health_score": timedelta(seconds=10),
        "incident_correlation": timedelta(seconds=5),
        "forecast": timedelta(seconds=30),
        "incident_summary": timedelta(seconds=10),
        "failure_prediction": timedelta(seconds=15),
        "idle_reclaim": timedelta(seconds=5),
        "maintenance_transition": timedelta(seconds=5),
        "security_monitoring": timedelta(seconds=5),
    }
