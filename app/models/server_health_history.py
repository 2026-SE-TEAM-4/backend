"""건강점수 이력(UC23). 추세 기울기 계산용 경량 시계열.

건강점수 잡(health_score_job)이 한 서버의 점수를 산출할 때마다 한 행씩 덧붙인다.
Server.health_score 는 최신값만 들고 있어 추세(7일 기울기)를 낼 수 없으므로, 시점별
점수를 따로 보관한다. 장애 예측 잡(failure_prediction_job)이 이 이력으로 기울기를 본다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerHealthHistory(Base):
    __tablename__ = "server_health_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 추세 조회가 server_id 로 필터하므로 인덱스를 명시한다(Postgres FK 자동 인덱싱 없음).
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("server.id"), index=True
    )
    score: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
