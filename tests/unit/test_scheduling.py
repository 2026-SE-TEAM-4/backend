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

    intervals = _intervals_by_id(scheduler)
    assert intervals == {
        "reservation_transitions": timedelta(minutes=1),
        "approval_timeout": timedelta(minutes=1),
        "metric_collection": timedelta(minutes=1),
        "anomaly_detection": timedelta(minutes=5),
        "health_score": timedelta(minutes=10),
        "incident_correlation": timedelta(minutes=5),
        "forecast": timedelta(minutes=60),
    }
