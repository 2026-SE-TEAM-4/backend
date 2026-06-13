"""보안 이벤트 기록 헬퍼(UC26 F36).

얇은 래퍼로, 호출부가 severity·필드를 결정하면 SecurityEvent 를 세션에 추가한다.
커밋은 호출부(라우터·잡)가 책임진다. FastAPI 를 알지 않는다.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import IncidentSeverity
from app.models.security_event import SecurityEvent


def record_event(
    db: AsyncSession,
    *,
    event_type: str,
    severity: str = IncidentSeverity.INFO.value,
    actor_id: int | None = None,
    source_ip: str | None = None,
    identifier: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """SecurityEvent 를 세션에 추가한다. 커밋은 호출부가 한다."""
    db.add(SecurityEvent(
        event_type=event_type,
        severity=severity,
        actor_id=actor_id,
        source_ip=source_ip,
        identifier=identifier,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    ))
