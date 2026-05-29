"""이상 징후 이력(UC18). 평균(mean)·표준편차(stddev) 기준 이탈 기록."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnomalyRecord(Base):
    __tablename__ = "anomaly_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("server.id"))
    current_value: Mapped[float] = mapped_column(Float)
    mean: Mapped[float] = mapped_column(Float)
    stddev: Mapped[float] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
