"""APScheduler 진입점 (별도 컨테이너).

지금은 등록된 잡이 없다. 자동화 잡(UC14·15·16·18·19)은 후속 단계에서
services/jobs를 재사용해 등록한다. 프로세스는 잡 대기를 위해 살려 둔다.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler")


async def main() -> None:
    scheduler = AsyncIOScheduler()
    scheduler.start()
    logger.info("스케줄러 시작됨 (등록된 잡 없음, 기본 주기=%ss)", settings.scheduler_interval_sec)
    # 잡 등록 전이므로 이벤트 대기로 프로세스를 유지한다.
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
