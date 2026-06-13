"""보안 위협 탐지 순수 로직(UC27 F37).

DB·스케줄러 비의존. security_monitoring_job 이 조회한 이벤트를 넘겨 호출한다.
임계값과 윈도우는 모듈 상수로 선언한다 — 데모 가속용 낮은 값이다.
"""

from dataclasses import dataclass
from datetime import timedelta

from app.models.enums import IncidentSeverity, SecurityAlertType, SecurityEventType

# --- 윈도우·임계 상수 -----------------------------------------------------------

# 브루트포스: source_ip 또는 identifier 기준, 60초 내 로그인 실패+잠금 ≥ 5
BRUTE_FORCE_WINDOW = timedelta(seconds=60)
BRUTE_FORCE_THRESHOLD = 5

# 접근 남용: actor_id 기준, 60초 내 ACCESS_DENIED ≥ 5
ACCESS_ABUSE_WINDOW = timedelta(seconds=60)
ACCESS_ABUSE_THRESHOLD = 5

# 에이전트 다운: server:{id} 기준, 30초 내 AGENT_UNREACHABLE ≥ 3
AGENT_DOWN_WINDOW = timedelta(seconds=30)
AGENT_DOWN_THRESHOLD = 3

# 관리자 남용: actor_id 기준, 60초 내 ADMIN_ACTION ≥ 5
ADMIN_ABUSE_WINDOW = timedelta(seconds=60)
ADMIN_ABUSE_THRESHOLD = 5

# 브루트포스 이벤트 종류(잠금 포함 시 CRITICAL 로 올린다).
_BRUTE_FORCE_TYPES = {
    SecurityEventType.LOGIN_FAILURE.value,
    SecurityEventType.ACCOUNT_LOCKED.value,
}


@dataclass(frozen=True)
class AlertDecision:
    """탐지 판정 결과. 경보를 생성해야 하면 should_alert=True."""

    should_alert: bool
    alert_type: str
    subject: str
    severity: str
    event_count: int
    message: str


def evaluate_brute_force(
    subject: str,
    events: list[dict],
    *,
    has_lock_event: bool = False,
) -> AlertDecision:
    """브루트포스 여부를 판정한다.

    subject 는 source_ip 또는 identifier(이메일) 중 집계 키로 쓰인 값을 넘긴다.
    has_lock_event 가 True 이면 계정 잠금이 포함된 것이므로 CRITICAL 로 올린다.
    """
    count = len(events)
    if count < BRUTE_FORCE_THRESHOLD:
        return AlertDecision(
            should_alert=False,
            alert_type=SecurityAlertType.BRUTE_FORCE.value,
            subject=subject,
            severity=IncidentSeverity.WARNING.value,
            event_count=count,
            message="",
        )
    severity = (
        IncidentSeverity.CRITICAL.value if has_lock_event
        else IncidentSeverity.WARNING.value
    )
    return AlertDecision(
        should_alert=True,
        alert_type=SecurityAlertType.BRUTE_FORCE.value,
        subject=subject,
        severity=severity,
        event_count=count,
        message=f"브루트포스 의심: {subject} 에서 {count}회 로그인 실패",
    )


def evaluate_access_abuse(actor_id: int, events: list[dict]) -> AlertDecision:
    """접근 권한 남용 여부를 판정한다."""
    count = len(events)
    subject = f"user:{actor_id}"
    if count < ACCESS_ABUSE_THRESHOLD:
        return AlertDecision(
            should_alert=False,
            alert_type=SecurityAlertType.ACCESS_ABUSE.value,
            subject=subject,
            severity=IncidentSeverity.WARNING.value,
            event_count=count,
            message="",
        )
    return AlertDecision(
        should_alert=True,
        alert_type=SecurityAlertType.ACCESS_ABUSE.value,
        subject=subject,
        severity=IncidentSeverity.WARNING.value,
        event_count=count,
        message=f"접근 권한 남용 의심: 사용자 {actor_id} 가 {count}회 거부됨",
    )


def evaluate_agent_down(server_id: int, events: list[dict]) -> AlertDecision:
    """에이전트 다운 여부를 판정한다."""
    count = len(events)
    subject = f"server:{server_id}"
    if count < AGENT_DOWN_THRESHOLD:
        return AlertDecision(
            should_alert=False,
            alert_type=SecurityAlertType.AGENT_DOWN.value,
            subject=subject,
            severity=IncidentSeverity.CRITICAL.value,
            event_count=count,
            message="",
        )
    return AlertDecision(
        should_alert=True,
        alert_type=SecurityAlertType.AGENT_DOWN.value,
        subject=subject,
        severity=IncidentSeverity.CRITICAL.value,
        event_count=count,
        message=f"에이전트 다운 의심: 서버 {server_id} 가 {count}회 응답 없음",
    )


def evaluate_admin_abuse(actor_id: int, events: list[dict]) -> AlertDecision:
    """관리자 작업 남용 여부를 판정한다."""
    count = len(events)
    subject = f"user:{actor_id}"
    if count < ADMIN_ABUSE_THRESHOLD:
        return AlertDecision(
            should_alert=False,
            alert_type=SecurityAlertType.ADMIN_ABUSE.value,
            subject=subject,
            severity=IncidentSeverity.WARNING.value,
            event_count=count,
            message="",
        )
    return AlertDecision(
        should_alert=True,
        alert_type=SecurityAlertType.ADMIN_ABUSE.value,
        subject=subject,
        severity=IncidentSeverity.WARNING.value,
        event_count=count,
        message=f"관리자 작업 남용 의심: 사용자 {actor_id} 가 {count}회 민감 작업 수행",
    )
