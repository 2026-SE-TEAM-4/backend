"""승인 타임아웃 자동 거절 스케줄러 잡 [UC17].

1분 주기로 실행. PENDING 상태로 72시간을 초과한 ApprovalRequest를
AUTO_REJECTED로 전환한다.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApprovalRequest
from app.models.enums import ApprovalStatus

logger = logging.getLogger(__name__)

_TIMEOUT = timedelta(hours=72)


async def auto_reject_timed_out_requests() -> None:
    """72시간 초과 PENDING 요청을 AUTO_REJECTED로 전환한다."""
    async with SessionLocal() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            cutoff = now - _TIMEOUT

            rows = await db.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.status == ApprovalStatus.PENDING.value,
                    ApprovalRequest.requested_at <= cutoff,
                )
            )
            requests = rows.scalars().all()

            for req in requests:
                req.status = ApprovalStatus.AUTO_REJECTED.value
                req.decided_at = now
                req.decided_by = "SYSTEM"
                logger.info("승인 요청 %d → AUTO_REJECTED (72시간 초과)", req.id)

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("승인 타임아웃 자동 거절 잡 실패")
