"""서버풀 메트릭 수집 잡(P0, UC14 기반).

1분 주기로 모든 활성 서버의 server-pool 에이전트 /metrics 를 풀(pull)해 ServerMetric 에
적재한다. 이상탐지(F27)·건강점수(F28)·예측이 모두 이 데이터 위에서 동작한다.

세션 팩토리와 HTTP 클라이언트는 외부 의존(데이터 출처) 경계라 인자로 받는다.
기본값은 운영용(SessionLocal, 새 httpx 클라이언트), 테스트는 컨테이너·MockTransport를 넘긴다.
"""

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import Server, ServerMetric
from app.models.enums import IncidentSeverity, MetricStatus, SecurityEventType
from app.services.metric_ingest import agent_metrics_url, parse_metric_payload
from app.services.scheduler_log import add_scheduler_log
from app.services.security_event_service import record_event

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(3.0)


async def collect_server_metrics(
    *,
    session_factory: async_sessionmaker = SessionLocal,
    client: httpx.AsyncClient | None = None,
) -> None:
    """활성 서버별 에이전트를 호출해 메트릭 한 건씩 적재한다."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        async with session_factory() as db:
            try:
                servers = (
                    await db.execute(select(Server).where(Server.deleted_at.is_(None)))
                ).scalars().all()
                for server in servers:
                    metric = await _read_metric(client, server.id)
                    db.add(metric)
                    # 에이전트 무응답 시 보안 이벤트도 함께 기록한다.
                    if metric.status == MetricStatus.MISSING.value:
                        record_event(
                            db,
                            event_type=SecurityEventType.AGENT_UNREACHABLE.value,
                            severity=IncidentSeverity.WARNING.value,
                            target_type="server",
                            target_id=str(server.id),
                        )
                # 대시보드(F21)용 실행 이력: 이번에 메트릭을 적재한 서버 수를 처리량으로 남긴다.
                add_scheduler_log(db, "UC14", len(servers))
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("메트릭 수집 잡 실패")
    finally:
        if owns_client:
            await client.aclose()


async def _read_metric(client: httpx.AsyncClient, server_id: int) -> ServerMetric:
    """에이전트를 호출해 ServerMetric 을 만든다. 실패하면 MISSING 으로 기록한다."""
    url = agent_metrics_url(settings.serverpool_host, settings.serverpool_base_port, server_id)
    try:
        response = await client.get(url)
        response.raise_for_status()
        parsed = parse_metric_payload(response.json())
        return ServerMetric(
            server_id=server_id,
            cpu_usage=parsed.cpu_usage,
            mem_usage=parsed.mem_usage,
            net_usage=parsed.net_usage,
            gpu_usage=parsed.gpu_usage,
            status=MetricStatus.OK.value,
        )
    except (httpx.HTTPError, KeyError, ValueError):
        # 무응답·계약 위반은 수집 품질을 데이터로 남긴다(MISSING). 건강점수가 이를 감점한다.
        logger.warning("서버 %d 메트릭 수집 실패 → MISSING 기록", server_id)
        return ServerMetric(
            server_id=server_id,
            cpu_usage=0.0,
            mem_usage=0.0,
            net_usage=0.0,
            gpu_usage=None,
            status=MetricStatus.MISSING.value,
        )
