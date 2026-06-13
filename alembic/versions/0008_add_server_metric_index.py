"""add composite index on server_metric(server_id, collected_at)

가용성·이상탐지·건강점수 잡이 (server_id, collected_at) 조합으로 조회하므로
복합 인덱스를 추가한다. 잡 주기를 단축했을 때 쿼리 빈도가 크게 늘어
시퀀셜 스캔을 인덱스 스캔으로 대체하는 효과가 즉시 나타난다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_server_metric_server_id_collected_at"


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(existing["name"] == index for existing in inspector.get_indexes(table))


def upgrade() -> None:
    if not _has_index("server_metric", _INDEX_NAME):
        op.create_index(_INDEX_NAME, "server_metric", ["server_id", "collected_at"])


def downgrade() -> None:
    if _has_index("server_metric", _INDEX_NAME):
        op.drop_index(_INDEX_NAME, table_name="server_metric")
