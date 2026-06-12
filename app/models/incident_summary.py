"""인시던트 LLM 원인 요약(UC25). 요약 잡이 저장하고 API 가 읽기 전용으로 조회한다.

요약 잡(incident_summary_job)이 OPEN 인시던트의 묶인 이상·관련 메트릭·서버 메타를
모아 LLM 에 보내고, 돌려받은 상황·원인 후보·권장 조치를 한 행으로 저장한다.
인시던트당 한 번만 생성하고(비용 절감), 이후 조회는 이 행을 그대로 읽는다.

root_causes 는 [{cause, evidence}], recommendations 는 [{action, rationale}] 형태의
JSONB 리스트다. 항목 수가 가변이라 컬럼화하지 않는다. model 은 요약을 만든 모델 id 다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IncidentSummary(Base):
    __tablename__ = "incident_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 어떤 인시던트의 요약인지. 조회·중복생성 방지가 모두 incident_id 로 필터하므로
    # 인덱스를 명시한다(Postgres 는 FK 컬럼을 자동 인덱싱하지 않는다).
    incident_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("incident.id"), index=True
    )
    situation: Mapped[str] = mapped_column(Text)
    # [{cause, evidence}] / [{action, rationale}]. 항목 수가 가변이라 JSONB 로 둔다.
    root_causes: Mapped[list[dict]] = mapped_column(JSONB)
    recommendations: Mapped[list[dict]] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
