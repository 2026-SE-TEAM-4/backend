"""보안 위협 탐지 순수 로직 단위 테스트(경계값 중심).

각 규칙의 임계 바로 아래·정확히 임계·초과 세 경우를 검증한다.
DB 없이 판정 함수만 테스트한다.
"""

from app.models.enums import IncidentSeverity, SecurityAlertType
from app.services.security_detection import (
    ADMIN_ABUSE_THRESHOLD,
    ACCESS_ABUSE_THRESHOLD,
    AGENT_DOWN_THRESHOLD,
    BRUTE_FORCE_THRESHOLD,
    evaluate_access_abuse,
    evaluate_admin_abuse,
    evaluate_agent_down,
    evaluate_brute_force,
)


# --- 브루트포스 -----------------------------------------------------------

def test_brute_force_below_threshold():
    events = [{}] * (BRUTE_FORCE_THRESHOLD - 1)
    result = evaluate_brute_force("1.2.3.4", events)
    assert result.should_alert is False


def test_brute_force_at_threshold():
    events = [{}] * BRUTE_FORCE_THRESHOLD
    result = evaluate_brute_force("1.2.3.4", events)
    assert result.should_alert is True
    assert result.alert_type == SecurityAlertType.BRUTE_FORCE.value
    assert result.severity == IncidentSeverity.WARNING.value


def test_brute_force_above_threshold():
    events = [{}] * (BRUTE_FORCE_THRESHOLD + 3)
    result = evaluate_brute_force("1.2.3.4", events)
    assert result.should_alert is True
    assert result.event_count == BRUTE_FORCE_THRESHOLD + 3


def test_brute_force_critical_when_lock_event():
    events = [{}] * BRUTE_FORCE_THRESHOLD
    result = evaluate_brute_force("1.2.3.4", events, has_lock_event=True)
    assert result.should_alert is True
    assert result.severity == IncidentSeverity.CRITICAL.value


def test_brute_force_warning_without_lock_event():
    events = [{}] * BRUTE_FORCE_THRESHOLD
    result = evaluate_brute_force("1.2.3.4", events, has_lock_event=False)
    assert result.severity == IncidentSeverity.WARNING.value


# --- 접근 남용 -----------------------------------------------------------

def test_access_abuse_below_threshold():
    events = [{}] * (ACCESS_ABUSE_THRESHOLD - 1)
    result = evaluate_access_abuse(42, events)
    assert result.should_alert is False


def test_access_abuse_at_threshold():
    events = [{}] * ACCESS_ABUSE_THRESHOLD
    result = evaluate_access_abuse(42, events)
    assert result.should_alert is True
    assert result.alert_type == SecurityAlertType.ACCESS_ABUSE.value
    assert result.subject == "user:42"


def test_access_abuse_above_threshold():
    events = [{}] * (ACCESS_ABUSE_THRESHOLD + 2)
    result = evaluate_access_abuse(42, events)
    assert result.should_alert is True
    assert result.event_count == ACCESS_ABUSE_THRESHOLD + 2


# --- 에이전트 다운 --------------------------------------------------------

def test_agent_down_below_threshold():
    events = [{}] * (AGENT_DOWN_THRESHOLD - 1)
    result = evaluate_agent_down(3, events)
    assert result.should_alert is False


def test_agent_down_at_threshold():
    events = [{}] * AGENT_DOWN_THRESHOLD
    result = evaluate_agent_down(3, events)
    assert result.should_alert is True
    assert result.alert_type == SecurityAlertType.AGENT_DOWN.value
    assert result.severity == IncidentSeverity.CRITICAL.value
    assert result.subject == "server:3"


def test_agent_down_above_threshold():
    events = [{}] * (AGENT_DOWN_THRESHOLD + 5)
    result = evaluate_agent_down(3, events)
    assert result.should_alert is True
    assert result.event_count == AGENT_DOWN_THRESHOLD + 5


# --- 관리자 남용 ----------------------------------------------------------

def test_admin_abuse_below_threshold():
    events = [{}] * (ADMIN_ABUSE_THRESHOLD - 1)
    result = evaluate_admin_abuse(7, events)
    assert result.should_alert is False


def test_admin_abuse_at_threshold():
    events = [{}] * ADMIN_ABUSE_THRESHOLD
    result = evaluate_admin_abuse(7, events)
    assert result.should_alert is True
    assert result.alert_type == SecurityAlertType.ADMIN_ABUSE.value
    assert result.subject == "user:7"


def test_admin_abuse_above_threshold():
    events = [{}] * (ADMIN_ABUSE_THRESHOLD + 1)
    result = evaluate_admin_abuse(7, events)
    assert result.should_alert is True
    assert result.event_count == ADMIN_ABUSE_THRESHOLD + 1
