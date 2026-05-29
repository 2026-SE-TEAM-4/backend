"""스케줄러 실행 로그(UC21 운영 대시보드의 데이터 소스)."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SchedulerLog(Base):
    __tablename__ = "scheduler_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    uc_id: Mapped[str] = mapped_column(String(20))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    success: Mapped[bool] = mapped_column(Boolean)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
