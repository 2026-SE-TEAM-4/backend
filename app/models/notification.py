"""사용자 알림. payload는 JSON, read_at으로 읽음 처리."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"))
    # 값 목록이 SSOT에서 미확정이라 평문 문자열로 둔다(후속 Enum화).
    type: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
