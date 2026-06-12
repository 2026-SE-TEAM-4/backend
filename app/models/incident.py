"""인시던트(UC24). 상관된 이상들을 하나로 묶어 노이즈를 줄인다.

상관 잡(incident_correlation_job)이 미할당 이상들을 서버 그룹·시간 윈도우로 묶어
인시던트 하나로 만든다. AnomalyRecord.incident_id 가 묶임을 가리킨다.
server_ids 는 이 인시던트와 관련된 서버 id 목록(JSONB)이다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import IncidentSeverity, IncidentStatus


class Incident(Base):
    __tablename__ = "incident"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    severity: Mapped[str] = mapped_column(String(10), default=IncidentSeverity.INFO.value)
    status: Mapped[str] = mapped_column(String(10), default=IncidentStatus.OPEN.value)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)
    # 관련 서버 id 목록. JSONB 리스트로 둔다(서버 수가 가변이라 컬럼화하지 않는다).
    server_ids: Mapped[list[int]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
