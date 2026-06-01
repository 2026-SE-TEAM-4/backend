"""add server_metric.gpu_usage — GPU 사용률 컬럼 (서버풀 /metrics gpuUsage 반영)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-01

서버풀 /metrics 계약이 gpuUsage(GPU 사용률)를 노출하도록 확정됨에 따라
ServerMetric에 nullable gpu_usage 컬럼을 추가한다. GPU 공유가 핵심 도메인이므로
사용률 시계열에 GPU를 포함한다. GPU 미탑재 노드는 null.

베이스라인 0001은 모델 메타데이터로 create_all 하므로, 모델에 gpu_usage가 추가된
fresh DB는 0001 시점에 이미 컬럼을 갖는다. 따라서 존재 여부를 검사해 멱등하게
처리한다(이미 0001을 적용한 기존 DB에는 컬럼을 더한다).
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("server_metric", "gpu_usage"):
        op.add_column("server_metric", sa.Column("gpu_usage", sa.Float(), nullable=True))


def downgrade() -> None:
    if _has_column("server_metric", "gpu_usage"):
        op.drop_column("server_metric", "gpu_usage")
