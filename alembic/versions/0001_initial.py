"""initial schema — ERD 13개 엔티티 (베이스라인)

Revision ID: 0001
Revises:
Create Date: 2026-05-29

ORM 메타데이터로 13개 테이블을 한 번에 생성하는 베이스라인 마이그레이션이다.
모델이 단일 출처이므로 마이그레이션과 모델이 어긋날 일이 없다.
이후 스키마 변경은 `alembic revision --autogenerate -m "..."`로 만든다.
"""

from alembic import op

import app.models  # noqa: F401  메타데이터 등록
from app.database import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
