"""APScheduler 진입점 (별도 컨테이너).

모든 주기 잡을 이 프로세스가 단독 소유한다. 잡 등록은 jobs/scheduling.py 한 곳에 모은다.
API 프로세스(main.py)는 잡을 돌리지 않으므로 이중 실행이 발생하지 않는다.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.jobs.scheduling import register_jobs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler")


async def main() -> None:
    scheduler = AsyncIOScheduler()
    register_jobs(scheduler)
    scheduler.start()
    logger.info("스케줄러 시작됨 (기본 주기=%ss)", settings.scheduler_interval_sec)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())