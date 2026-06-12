"""add incident table + anomaly_record.incident_id FK (UC24 인시던트 상관 반영)

상관 잡(incident_correlation_job)이 미할당 이상들을 인시던트로 묶기 시작하면서
incident 테이블과, 이상이 어느 인시던트에 묶였는지 가리키는 anomaly_record.incident_id
FK 가 필요하다. FK 가 incident.id 를 참조하므로 테이블을 먼저 만든 뒤 컬럼을 더한다.

베이스라인 0001은 모델 메타데이터로 create_all 하므로, 모델에 incident/incident_id 가
추가된 fresh DB 는 0001 시점에 이미 갖는다. 0002·0003 과 동일하게 존재 여부를 검사해
멱등하게 처리한다(이미 적용한 기존 DB 에는 더한다).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_table("incident"):
        op.create_table(
            "incident",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("severity", sa.String(length=10), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("anomaly_count", sa.Integer(), nullable=False),
            sa.Column("server_ids", JSONB(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_column("anomaly_record", "incident_id"):
        op.add_column(
            "anomaly_record",
            sa.Column("incident_id", sa.BigInteger(), nullable=True),
        )
        op.create_foreign_key(
            "fk_anomaly_record_incident_id",
            "anomaly_record",
            "incident",
            ["incident_id"],
            ["id"],
        )


def _incident_fk_name() -> str | None:
    """anomaly_record.incident_id 의 실제 FK 제약 이름을 찾는다(없으면 None).

    베이스라인 0001(create_all)이 만든 DB 는 SQLAlchemy 기본 이름
    (anomaly_record_incident_id_fkey)을, 0003→0004 업그레이드 경로는 명시 이름을
    쓰므로, 이름을 검사로 알아내 downgrade 가 두 경로 모두에서 동작하게 한다.
    """
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys("anomaly_record"):
        if fk["referred_table"] == "incident":
            return fk["name"]
    return None


def downgrade() -> None:
    if _has_column("anomaly_record", "incident_id"):
        fk_name = _incident_fk_name()
        if fk_name is not None:
            op.drop_constraint(fk_name, "anomaly_record", type_="foreignkey")
        op.drop_column("anomaly_record", "incident_id")
    if _has_table("incident"):
        op.drop_table("incident")
