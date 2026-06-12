"""이상 징후 이력(UC18). 평균(mean)·표준편차(stddev) 기준 이탈 기록."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnomalyRecord(Base):
    __tablename__ = "anomaly_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("server.id"))
    # 어떤 메트릭이 이탈했는지(MetricType: CPU/MEM/NET/GPU). 유형별 묶기·설명의 기준.
    metric: Mapped[str] = mapped_column(String(10))
    current_value: Mapped[float] = mapped_column(Float)
    mean: Mapped[float] = mapped_column(Float)
    stddev: Mapped[float] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 상관 잡이 이 이상을 묶은 인시던트(UC24). 미할당이면 NULL.
    # Postgres 는 FK 컬럼을 자동 인덱싱하지 않는데, 상관/조회/자동종료가 모두
    # incident_id 로 필터하므로 인덱스를 명시한다.
    incident_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("incident.id"), nullable=True, index=True
    )
