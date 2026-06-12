"""add anomaly_record.metric — 이탈 메트릭 종류 컬럼 (UC18 이상탐지 구현 반영)

이상탐지 잡이 AnomalyRecord 를 기록하기 시작하면서, 어떤 메트릭(CPU/MEM/NET/GPU)이
기준선을 벗어났는지 구분해야 한다(유형별 묶기·원인 설명의 기준). metric 컬럼을 추가한다.

베이스라인 0001은 모델 메타데이터로 create_all 하므로, 모델에 metric이 추가된 fresh DB는
0001 시점에 이미 컬럼을 갖는다. 0002와 동일하게 존재 여부를 검사해 멱등하게 처리한다.
anomaly_record 는 아직 적재 잡이 없어 비어 있으므로 NOT NULL 추가가 안전하다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("anomaly_record", "metric"):
        op.add_column("anomaly_record", sa.Column("metric", sa.String(10), nullable=False))


def downgrade() -> None:
    if _has_column("anomaly_record", "metric"):
        op.drop_column("anomaly_record", "metric")
