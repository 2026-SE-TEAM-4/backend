"""APScheduler 진입점 (별도 컨테이너)."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler")


async def main() -> None:
    scheduler = AsyncIOScheduler()
    scheduler.start()
    logger.info("스케줄러 시작됨 (기본 주기=%ss)", settings.scheduler_interval_sec)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())