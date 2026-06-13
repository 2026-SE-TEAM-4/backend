"""보안 위협 탐지·경보 잡(F37, UC27).

5초 주기로 최근 SecurityEvent 를 윈도우별로 집계해 위협 패턴을 탐지한다.
임계를 넘으면 SecurityAlert 를 생성하고, 같은 alert_type+subject 의 OPEN 경보가
이미 있으면 event_count 만 갱신한다(디바운스).
경보 생성 시 전체 ADM 사용자에게 Notification 을 만들고 WS 채널에 발행한다.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.redis import publish_notification
from app.database import SessionLocal
from app.models import Notification, SecurityAlert, SecurityEvent, User
from app.models.enums import IncidentStatus, SecurityEventType, UserRole
from app.services.scheduler_log import add_scheduler_log
from app.services.security_detection import (
    ACCESS_ABUSE_WINDOW,
    ADMIN_ABUSE_WINDOW,
    AGENT_DOWN_WINDOW,
    BRUTE_FORCE_WINDOW,
    AlertDecision,
    _BRUTE_FORCE_TYPES,
    evaluate_access_abuse,
    evaluate_admin_abuse,
    evaluate_agent_down,
    evaluate_brute_force,
)

logger = logging.getLogger(__name__)


async def detect_security_threats(
    *, session_factory: async_sessionmaker = SessionLocal
) -> None:
    """최근 보안 이벤트를 집계해 위협 패턴을 탐지·경보한다."""
    async with session_factory() as db:
        try:
            now = datetime.now(tz=timezone.utc)
            decisions = await _collect_decisions(db, now)

            created = 0
            for decision in decisions:
                if not decision.should_alert:
                    continue
                created += await _upsert_alert(db, decision, now)

            add_scheduler_log(db, "UC27", created)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("보안 탐지 잡 실패")


async def _collect_decisions(db: AsyncSession, now: datetime) -> list[AlertDecision]:
    """4가지 위협 패턴을 각각 집계해 판정 목록을 만든다."""
    decisions: list[AlertDecision] = []

    # 1. 브루트포스: source_ip 또는 identifier 기준
    decisions.extend(await _detect_brute_force(db, now))

    # 2. 접근 남용: actor_id 기준
    decisions.extend(await _detect_access_abuse(db, now))

    # 3. 에이전트 다운: server_id(target_id) 기준
    decisions.extend(await _detect_agent_down(db, now))

    # 4. 관리자 남용: actor_id 기준
    decisions.extend(await _detect_admin_abuse(db, now))

    return decisions


async def _recent_events(
    db: AsyncSession, event_type: str, since: datetime
) -> list[SecurityEvent]:
    """event_type 과 시각 범위로 최근 SecurityEvent 를 가져온다."""
    rows = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type == event_type,
            SecurityEvent.occurred_at >= since,
        )
    )
    return list(rows.scalars().all())


async def _recent_events_in(
    db: AsyncSession, event_types: list[str], since: datetime
) -> list[SecurityEvent]:
    """여러 event_type 를 한 번에 가져온다."""
    rows = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type.in_(event_types),
            SecurityEvent.occurred_at >= since,
        )
    )
    return list(rows.scalars().all())


async def _detect_brute_force(
    db: AsyncSession, now: datetime
) -> list[AlertDecision]:
    """IP 또는 이메일 기준 로그인 실패+잠금 브루트포스 탐지."""
    since = now - BRUTE_FORCE_WINDOW
    events = await _recent_events_in(db, list(_BRUTE_FORCE_TYPES), since)

    # source_ip 와 identifier 각각으로 집계한다.
    by_ip: dict[str, list] = defaultdict(list)
    by_id: dict[str, list] = defaultdict(list)
    for ev in events:
        if ev.source_ip:
            by_ip[ev.source_ip].append(ev)
        if ev.identifier:
            by_id[ev.identifier].append(ev)

    decisions = []
    for ip, evs in by_ip.items():
        has_lock = any(
            e.event_type == SecurityEventType.ACCOUNT_LOCKED.value for e in evs
        )
        decisions.append(evaluate_brute_force(ip, evs, has_lock_event=has_lock))

    for ident, evs in by_id.items():
        has_lock = any(
            e.event_type == SecurityEventType.ACCOUNT_LOCKED.value for e in evs
        )
        decisions.append(evaluate_brute_force(ident, evs, has_lock_event=has_lock))

    return decisions


async def _detect_access_abuse(
    db: AsyncSession, now: datetime
) -> list[AlertDecision]:
    """actor_id 기준 ACCESS_DENIED 남용 탐지."""
    since = now - ACCESS_ABUSE_WINDOW
    events = await _recent_events(db, SecurityEventType.ACCESS_DENIED.value, since)

    by_actor: dict[int, list] = defaultdict(list)
    for ev in events:
        if ev.actor_id is not None:
            by_actor[ev.actor_id].append(ev)

    return [evaluate_access_abuse(actor_id, evs) for actor_id, evs in by_actor.items()]


async def _detect_agent_down(
    db: AsyncSession, now: datetime
) -> list[AlertDecision]:
    """server_id 기준 AGENT_UNREACHABLE 탐지."""
    since = now - AGENT_DOWN_WINDOW
    events = await _recent_events(db, SecurityEventType.AGENT_UNREACHABLE.value, since)

    by_server: dict[str, list] = defaultdict(list)
    for ev in events:
        if ev.target_id is not None:
            by_server[ev.target_id].append(ev)

    decisions = []
    for server_id_str, evs in by_server.items():
        try:
            server_id = int(server_id_str)
        except ValueError:
            continue
        decisions.append(evaluate_agent_down(server_id, evs))
    return decisions


async def _detect_admin_abuse(
    db: AsyncSession, now: datetime
) -> list[AlertDecision]:
    """actor_id 기준 ADMIN_ACTION 남용 탐지."""
    since = now - ADMIN_ABUSE_WINDOW
    events = await _recent_events(db, SecurityEventType.ADMIN_ACTION.value, since)

    by_actor: dict[int, list] = defaultdict(list)
    for ev in events:
        if ev.actor_id is not None:
            by_actor[ev.actor_id].append(ev)

    return [evaluate_admin_abuse(actor_id, evs) for actor_id, evs in by_actor.items()]


async def _upsert_alert(
    db: AsyncSession, decision: AlertDecision, now: datetime
) -> int:
    """경보를 생성하거나 기존 OPEN 경보를 갱신한다. 새로 만들었으면 1, 갱신이면 0."""
    existing = await db.scalar(
        select(SecurityAlert).where(
            SecurityAlert.alert_type == decision.alert_type,
            SecurityAlert.subject == decision.subject,
            SecurityAlert.status == IncidentStatus.OPEN.value,
        )
    )
    if existing is not None:
        # 디바운스: 이미 열린 경보가 있으면 event_count 만 갱신한다.
        existing.event_count = decision.event_count
        return 0

    alert = SecurityAlert(
        alert_type=decision.alert_type,
        severity=decision.severity,
        status=IncidentStatus.OPEN.value,
        subject=decision.subject,
        event_count=decision.event_count,
        message=decision.message,
    )
    db.add(alert)
    # alert.id 를 쓰려면 flush 가 필요하다.
    await db.flush()

    await _notify_all_admins(db, alert)
    logger.info(
        "보안 경보 생성: %s (%s) — %s",
        decision.alert_type,
        decision.subject,
        decision.message,
    )
    return 1


async def _notify_all_admins(db: AsyncSession, alert: SecurityAlert) -> None:
    """전체 ADM 사용자에게 security_alert 알림을 만들고 WS 채널에 발행한다."""
    admins = (
        await db.execute(
            select(User).where(User.role == UserRole.ADM.value)
        )
    ).scalars().all()

    payload = {
        "alertId": alert.id,
        "alertType": alert.alert_type,
        "severity": alert.severity,
        "subject": alert.subject,
    }

    for admin in admins:
        db.add(Notification(
            user_id=admin.id,
            type="security_alert",
            message=alert.message,
            payload=payload,
        ))
        await publish_notification(admin.id, json.dumps(payload))
