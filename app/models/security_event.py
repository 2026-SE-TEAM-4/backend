"""보안 이벤트(UC26). 인증 실패·권한 거부·관리자 작업·에이전트 이상을 기록한다.

수집 출처별로 SecurityEventType 을 구분한다(enums.py). 탐지 잡(security_monitoring_job)이
이 테이블을 집계해 SecurityAlert 를 생성한다.

actor_id 는 nullable — 미가입 이메일이 로그인을 시도하면 사용자가 없기 때문이다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SecurityEvent(Base):
    __tablename__ = "security_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    # 익명 로그인 실패는 사용자가 없으므로 nullable.
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id"), nullable=True
    )
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # 시도된 이메일, 접근 경로 식별자 등.
    identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 경로·사유 등 부가 정보.
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 탐지 잡의 윈도우 집계(event_type + 시간 범위 WHERE)에 쓰이는 복합 인덱스.
    __table_args__ = (
        Index("ix_security_event_type_occurred", "event_type", "occurred_at"),
        Index("ix_security_event_source_ip", "source_ip"),
    )
