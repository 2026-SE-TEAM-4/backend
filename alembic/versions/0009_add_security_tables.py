"""security_event, security_alert 테이블 추가 (UC26·UC27 보안 관제)

보안 이벤트와 보안 경보를 저장하는 테이블 두 개를 만든다.
두 테이블 모두 user 테이블을 FK 참조하므로 user 테이블이 먼저 있어야 한다.
베이스라인(0001) create_all 경로에서는 이미 생성되어 있으므로 멱등 가드로 처리한다.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(idx["name"] == index for idx in inspector.get_indexes(table))


def upgrade() -> None:
    if not _has_table("security_event"):
        op.create_table(
            "security_event",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("event_type", sa.String(length=30), nullable=False),
            sa.Column("severity", sa.String(length=10), nullable=False),
            sa.Column("actor_id", sa.BigInteger(), nullable=True),
            sa.Column("source_ip", sa.String(length=45), nullable=True),
            sa.Column("identifier", sa.String(length=255), nullable=True),
            sa.Column("target_type", sa.String(length=50), nullable=True),
            sa.Column("target_id", sa.String(length=50), nullable=True),
            sa.Column("detail", JSONB(), nullable=True),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["actor_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index("security_event", "ix_security_event_type_occurred"):
        op.create_index(
            "ix_security_event_type_occurred",
            "security_event",
            ["event_type", "occurred_at"],
        )

    if not _has_index("security_event", "ix_security_event_source_ip"):
        op.create_index(
            "ix_security_event_source_ip",
            "security_event",
            ["source_ip"],
        )

    if not _has_table("security_alert"):
        op.create_table(
            "security_alert",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("alert_type", sa.String(length=20), nullable=False),
            sa.Column("severity", sa.String(length=10), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("event_count", sa.Integer(), nullable=False),
            sa.Column("message", sa.String(length=500), nullable=False),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(["resolved_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    if _has_table("security_alert"):
        op.drop_table("security_alert")

    if _has_index("security_event", "ix_security_event_source_ip"):
        op.drop_index("ix_security_event_source_ip", table_name="security_event")

    if _has_index("security_event", "ix_security_event_type_occurred"):
        op.drop_index("ix_security_event_type_occurred", table_name="security_event")

    if _has_table("security_event"):
        op.drop_table("security_event")
