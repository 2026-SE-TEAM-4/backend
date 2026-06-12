"""용량·수요 예측 결과(UC22). 예측 잡이 저장하고 API 가 읽기 전용으로 조회한다.

예측 잡(forecast_job)이 서버별 사용률(CPU/MEM/GPU)과 풀 전체 예약 수요를 Holt-Winters 로
예측해 한 행씩 저장한다. server_id 가 NULL 이면 풀 전체 예약 수요 예측이다.
horizon 은 향후 시점별 예측점 목록(JSONB)으로, [{ts, yhat, lower, upper}] 형태다.
saturation_at 은 예측값이 포화 임계를 처음 넘는 시각이며, 끝까지 넘지 않으면 NULL 이다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Forecast(Base):
    __tablename__ = "forecast"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # NULL 이면 풀 전체 예약 수요(RESERVATION_DEMAND), 값이 있으면 해당 서버 사용률 예측.
    server_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("server.id"), nullable=True
    )
    metric: Mapped[str] = mapped_column(String(20))  # ForecastMetric 값
    # 향후 시점별 예측점 목록 [{ts, yhat, lower, upper}]. 시점 수가 가변이라 JSONB 로 둔다.
    horizon: Mapped[list[dict]] = mapped_column(JSONB)
    # 예측값이 포화 임계를 처음 넘는 시각. 끝까지 넘지 않으면 NULL.
    saturation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
