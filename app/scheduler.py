"""APScheduler 진입점 (별도 컨테이너).

지금은 등록된 잡이 없다. 자동화 잡(UC14·15·16·18·19)은 후속 단계에서
services/jobs를 재사용해 등록한다. 프로세스는 잡 대기를 위해 살려 둔다.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.jobs.health import calculate_health_scores
from app.jobs.idle import reclaim_idle_servers
from app.jobs.monitoring import collect_metrics, detect_anomalies

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler")


async def main() -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(collect_metrics, "interval", seconds=settings.scheduler_interval_sec, id="collect_metrics")
    scheduler.add_job(detect_anomalies, "interval", minutes=5, id="detect_anomalies")
    scheduler.add_job(calculate_health_scores, "interval", minutes=10, id="calculate_health_scores")
    scheduler.add_job(reclaim_idle_servers, "interval", minutes=15, id="reclaim_idle_servers")
    scheduler.start()
    logger.info("스케줄러 시작됨 (메트릭 수집 주기=%ss)", settings.scheduler_interval_sec)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
