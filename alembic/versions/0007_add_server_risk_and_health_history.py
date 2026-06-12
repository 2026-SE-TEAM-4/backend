"""add server risk fields and server_health_history table (UC23 장애·열화 예측)

장애 예측 잡(failure_prediction_job)이 서버별 위험도(risk_score)와 위험 진입 예상
시각(eta_to_risk)을 저장하고, 추세 기울기를 위해 시점별 건강점수 이력
(server_health_history)을 본다. server_id 로 추세를 조회하므로 인덱스를 함께 만든다.

베이스라인 0001 은 모델 메타데이터로 create_all 하므로, 모델에 신규 컬럼·테이블이
추가된 fresh DB 는 0001 시점에 이미 갖는다. 0002~0006 과 동일하게 존재 여부를 검사해
멱등하게 처리한다(이미 적용한 기존 DB 에는 더한다).
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_server_health_history_server_id"


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(existing["name"] == column for existing in inspector.get_columns(table))


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(existing["name"] == index for existing in inspector.get_indexes(table))


def upgrade() -> None:
    if not _has_column("server", "risk_score"):
        op.add_column("server", sa.Column("risk_score", sa.Float(), nullable=True))
    if not _has_column("server", "eta_to_risk"):
        op.add_column(
            "server", sa.Column("eta_to_risk", sa.DateTime(timezone=True), nullable=True)
        )

    if not _has_table("server_health_history"):
        op.create_table(
            "server_health_history",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["server_id"], ["server.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    # create_all 로 만든 fresh DB 는 인덱스를 이미 갖는다. 기존 DB 에만 더한다.
    if not _has_index("server_health_history", _INDEX_NAME):
        op.create_index(_INDEX_NAME, "server_health_history", ["server_id"])


def downgrade() -> None:
    if _has_index("server_health_history", _INDEX_NAME):
        op.drop_index(_INDEX_NAME, table_name="server_health_history")
    if _has_table("server_health_history"):
        op.drop_table("server_health_history")
    if _has_column("server", "eta_to_risk"):
        op.drop_column("server", "eta_to_risk")
    if _has_column("server", "risk_score"):
        op.drop_column("server", "risk_score")
