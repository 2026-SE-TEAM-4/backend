"""대기열 항목(position). 사양 기반 대기 시 server_id는 비어 있을 수 있다."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class QueueEntry(Base):
    __tablename__ = "queue_entry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("server.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"))
    requested_spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
