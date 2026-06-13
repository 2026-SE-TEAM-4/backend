"""보안 경보(UC27). 탐지 잡이 위협 패턴을 찾아 생성한다.

SecurityEvent 를 집계해 임계를 넘으면 경보 1건으로 묶는다. 같은 alert_type + subject 의
OPEN 경보는 새로 만들지 않고 event_count 만 갱신한다(디바운스).
severity·status 는 IncidentSeverity·IncidentStatus 를 재사용한다(enums.py).
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SecurityAlert(Base):
    __tablename__ = "security_alert"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    # 기본값 OPEN. 관리자가 해결하면 RESOLVED 로 바꾼다.
    status: Mapped[str] = mapped_column(String(10), default="OPEN")
    # 경보 주체: IP 주소, 이메일, "server:{id}", "user:{id}" 등.
    subject: Mapped[str] = mapped_column(String(255))
    # 같은 경보에 묶인 이벤트 누적 수(디바운스 갱신 시 증가).
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(500))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id"), nullable=True
    )
