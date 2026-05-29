"""사용자별 한도·사용량. version으로 낙관적 잠금을 건다."""

from sqlalchemy import BigInteger, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Quota(Base):
    __tablename__ = "quota"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"))
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("team.id"))
    limit: Mapped[int] = mapped_column(Integer)
    used: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
