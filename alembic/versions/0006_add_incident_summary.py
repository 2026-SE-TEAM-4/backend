"""add incident_summary table (UC25 LLM 원인 요약 저장)

요약 잡(incident_summary_job)이 인시던트별 LLM 원인 요약을 저장하기 시작하면서
incident_summary 테이블이 필요하다. incident_id 로 조회·중복생성 방지가 일어나므로
인덱스를 함께 만든다.

베이스라인 0001 은 모델 메타데이터로 create_all 하므로, 모델에 incident_summary 가
추가된 fresh DB 는 0001 시점에 이미 갖는다. 0002~0005 와 동일하게 존재 여부를 검사해
멱등하게 처리한다(이미 적용한 기존 DB 에는 더한다).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_incident_summary_incident_id"


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table)


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(existing["name"] == index for existing in inspector.get_indexes(table))


def upgrade() -> None:
    if not _has_table("incident_summary"):
        op.create_table(
            "incident_summary",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("incident_id", sa.BigInteger(), nullable=False),
            sa.Column("situation", sa.Text(), nullable=False),
            sa.Column("root_causes", JSONB(), nullable=False),
            sa.Column("recommendations", JSONB(), nullable=False),
            sa.Column("model", sa.String(length=100), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    # create_all 로 만든 fresh DB 는 인덱스를 이미 갖는다. 기존 DB 에만 더한다.
    if not _has_index("incident_summary", _INDEX_NAME):
        op.create_index(_INDEX_NAME, "incident_summary", ["incident_id"])


def downgrade() -> None:
    if _has_index("incident_summary", _INDEX_NAME):
        op.drop_index(_INDEX_NAME, table_name="incident_summary")
    if _has_table("incident_summary"):
        op.drop_table("incident_summary")
