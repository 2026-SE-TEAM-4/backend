"""예약 한 건. 상태 생애주기(RESERVED → IN_USE → RETURNED/EXPIRED/RECLAIMED)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Reservation(Base):
    __tablename__ = "reservation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"))
    server_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("server.id"))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # ReservationStatus 값
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
