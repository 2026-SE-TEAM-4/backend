"""add forecast table (UC22 용량·수요 예측 결과 저장)

예측 잡(forecast_job)이 서버별 사용률·풀 전체 예약 수요 예측을 저장하기 시작하면서
forecast 테이블이 필요하다. server_id 는 NULL 허용(풀 전체 수요 예측은 서버에 속하지 않음).

베이스라인 0001 은 모델 메타데이터로 create_all 하므로, 모델에 forecast 가 추가된
fresh DB 는 0001 시점에 이미 갖는다. 0002~0004 와 동일하게 존재 여부를 검사해 멱등하게
처리한다(이미 적용한 기존 DB 에는 더한다).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table)


def upgrade() -> None:
    if not _has_table("forecast"):
        op.create_table(
            "forecast",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=True),
            sa.Column("metric", sa.String(length=20), nullable=False),
            sa.Column("horizon", JSONB(), nullable=False),
            sa.Column("saturation_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["server_id"], ["server.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    if _has_table("forecast"):
        op.drop_table("forecast")
