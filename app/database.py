"""SQLAlchemy 비동기 엔진·세션과 모든 모델이 상속하는 Base."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """모든 ORM 모델의 부모. 이 메타데이터가 마이그레이션의 기준이 된다."""
