"""LLM 원인 요약 잡(F34, UC25).

5분 주기로 아직 요약이 없는 OPEN 인시던트를 찾아, 묶인 이상·관련 메트릭·서버 메타를
모아 LLM 에 보내고 상황·원인 후보·권장 조치를 IncidentSummary 한 행으로 저장한다.
인시던트당 한 번만 생성한다(이미 요약이 있으면 다시 만들지 않는다 → 호출 비용 절감).

안전·보안:
- API 키는 settings.anthropic_api_key(환경 변수)에서만 온다. 비어 있으면 경고만 남기고
  건너뛴다(키 없이도 앱·다른 잡은 정상 동작).
- LLM 은 읽기 전용 분석만 한다(설계 D-4). 요약은 저장·표시만 하며 자동 조치는 없다.

테스트 용이성:
- Anthropic 클라이언트를 주입(client) 받는다. 기본값 None 이면 일이 있고 키가 있을 때만
  지연 생성한다. 테스트는 stub 클라이언트를 주입해 네트워크 없이 검증한다.
- 프롬프트 조립·응답 파싱은 순수 모듈(services/incident_summary)에 두어 결정적이다.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import AnomalyRecord, Incident, IncidentSummary, Server, ServerMetric
from app.models.enums import IncidentStatus
from app.services.incident_summary import build_context, build_prompt, parse_summary

logger = logging.getLogger(__name__)

# 한 인시던트 요약에 허용하는 최대 토큰. 상황·원인·권장 정도의 짧은 JSON 이면 충분하다.
_MAX_TOKENS = 1024
# 서버당 컨텍스트에 싣는 최근 메트릭 표본 수. 너무 많으면 토큰만 늘고 도움이 안 된다.
_METRIC_SAMPLES_PER_SERVER = 5


async def summarize_pending_incidents(
    *, session_factory: async_sessionmaker = SessionLocal, client=None
) -> None:
    """요약이 없는 OPEN 인시던트 각각에 LLM 원인 요약을 만들어 저장한다.

    키가 없으면 조용히 건너뛴다. 인시던트별 실패는 격리해 다른 인시던트 요약은 계속한다.
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY 가 없어 인시던트 요약 잡을 건너뜁니다.")
        return

    async with session_factory() as db:
        try:
            incidents = await _find_open_incidents_without_summary(db)
            if not incidents:
                return
            # 처리할 인시던트가 있고 키가 있을 때만 클라이언트를 지연 생성한다.
            client = client or _build_client()
            for incident in incidents:
                await _summarize_one(db, incident, client)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("인시던트 요약 잡 실패")


async def _find_open_incidents_without_summary(db: AsyncSession) -> list[Incident]:
    """요약이 아직 없는 OPEN 인시던트 목록을 가져온다.

    이미 IncidentSummary 가 있는 인시던트는 제외해 인시던트당 1회 생성을 보장한다.
    """
    summarized = select(IncidentSummary.incident_id)
    rows = await db.execute(
        select(Incident).where(
            Incident.status == IncidentStatus.OPEN.value,
            Incident.id.not_in(summarized),
        )
    )
    return list(rows.scalars().all())


async def _summarize_one(db: AsyncSession, incident: Incident, client) -> None:
    """한 인시던트의 컨텍스트를 모아 LLM 요약을 만들고 IncidentSummary 로 저장한다.

    한 인시던트의 실패(호출 오류·파싱 실패)가 전체 잡을 멈추지 않도록 여기서 잡아
    경고만 남기고 건너뛴다. 다른 인시던트는 계속 요약한다.
    """
    try:
        context = await _build_incident_context(db, incident)
        prompt = build_prompt(context)
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = parse_summary(_response_text(response))
        db.add(IncidentSummary(
            incident_id=incident.id,
            situation=parsed.situation,
            root_causes=parsed.root_causes,
            recommendations=parsed.recommendations,
            model=settings.anthropic_model,
        ))
    except Exception as error:
        logger.warning("인시던트 %s 요약 건너뜀: %s", incident.id, error)


async def _build_incident_context(db: AsyncSession, incident: Incident) -> dict:
    """인시던트에 묶인 이상·관련 서버·최근 메트릭을 조회해 평문 컨텍스트로 만든다."""
    anomalies = (
        await db.execute(
            select(AnomalyRecord)
            .where(AnomalyRecord.incident_id == incident.id)
            .order_by(AnomalyRecord.detected_at.desc())
        )
    ).scalars().all()

    server_ids = list(incident.server_ids or [])
    servers = (
        await db.execute(select(Server).where(Server.id.in_(server_ids)))
    ).scalars().all() if server_ids else []

    metrics = await _recent_metrics(db, server_ids)

    return build_context(
        incident={
            "id": incident.id,
            "severity": incident.severity,
            "status": incident.status,
            "server_ids": server_ids,
        },
        anomalies=[
            {
                "server_id": a.server_id,
                "metric": a.metric,
                "current_value": a.current_value,
                "mean": a.mean,
                "stddev": a.stddev,
                "detected_at": a.detected_at.isoformat() if a.detected_at else None,
            }
            for a in anomalies
        ],
        server_metrics=[
            {
                "server_id": m.server_id,
                "cpu_usage": m.cpu_usage,
                "mem_usage": m.mem_usage,
                "collected_at": m.collected_at.isoformat() if m.collected_at else None,
            }
            for m in metrics
        ],
        servers=[
            {"id": s.id, "name": s.name, "group_name": s.group_name} for s in servers
        ],
    )


async def _recent_metrics(db: AsyncSession, server_ids: list[int]) -> list[ServerMetric]:
    """관련 서버별 최근 메트릭 표본을 모은다(서버당 _METRIC_SAMPLES_PER_SERVER 건).

    인시던트 시점 전후 사용률을 LLM 이 근거로 인용할 수 있게 소량만 싣는다.
    """
    samples: list[ServerMetric] = []
    for server_id in server_ids:
        rows = (
            await db.execute(
                select(ServerMetric)
                .where(ServerMetric.server_id == server_id)
                .order_by(ServerMetric.collected_at.desc())
                .limit(_METRIC_SAMPLES_PER_SERVER)
            )
        ).scalars().all()
        samples.extend(rows)
    return samples


def _response_text(response) -> str:
    """Anthropic 응답 객체에서 텍스트 블록만 이어 붙인다.

    content 는 블록 리스트이고 텍스트 블록은 .text 를 갖는다. 텍스트가 아닌 블록은
    건너뛴다(요약 잡은 JSON 텍스트만 필요로 한다).
    """
    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "".join(parts)


def _build_client():
    """키가 있을 때만 Anthropic 비동기 클라이언트를 지연 생성한다.

    import 를 함수 안에 두는 이유: anthropic 패키지는 스케줄러 컨테이너에만 필요하고,
    이 잡이 실제로 일할 때만 의존하도록 하기 위함이다.
    """
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
