"""서버 사용률 시계열(UC14)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerMetric(Base):
    __tablename__ = "server_metric"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("server.id"))
    cpu_usage: Mapped[float] = mapped_column(Float)
    mem_usage: Mapped[float] = mapped_column(Float)
    net_usage: Mapped[float] = mapped_column(Float)
    # GPU 사용률(%). 서버풀 /metrics gpuUsage 계약과 매핑. GPU 미탑재 노드는 null.
    gpu_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 수집 품질(MetricStatus: OK/MISSING/NA). 에이전트는 OK만, 나머지는 수집기가 판정.
    status: Mapped[str] = mapped_column(String(20))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
