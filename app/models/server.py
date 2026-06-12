"""서버 자원. status·version·health_score·risk와 soft delete(deleted_at)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import ServerStatus


class Server(Base):
    __tablename__ = "server"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    ip: Mapped[str] = mapped_column(String(45))
    cpu_cores: Mapped[int] = mapped_column(Integer)
    ram_gb: Mapped[int] = mapped_column(Integer)
    gpu_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ServerStatus.AVAILABLE.value)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # health_score는 스케줄러가 메트릭으로 산출한다(후속).
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # UC23: 장애 예측 잡이 산출하는 0~100 위험도. version 미변경 직접 UPDATE 로만 쓴다.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # UC23: 건강점수가 위험 임계로 떨어질 것으로 예측되는 시각(열화 아니면 NULL).
    eta_to_risk: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
