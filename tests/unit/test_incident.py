"""인시던트 심각도 산출 순수 로직 단위 테스트(UC24). DB 없음.

이상 개수·관련 서버 수·최고 편차(σ 배수)로 INFO/WARNING/CRITICAL 을 정한다.
경계값에서 한 단계 위/아래가 갈리는지 확인한다(오분류 방지).
"""

from app.models.enums import IncidentSeverity
from app.services.incident import compute_severity


def test_single_anomaly_one_server_small_deviation_is_info():
    severity = compute_severity(anomaly_count=1, server_count=1, max_deviation=2.5)
    assert severity == IncidentSeverity.INFO.value


def test_moderate_anomalies_is_warning():
    # 이상 3건은 WARNING 임계에 도달한다.
    severity = compute_severity(anomaly_count=3, server_count=1, max_deviation=2.5)
    assert severity == IncidentSeverity.WARNING.value


def test_many_servers_escalates_to_critical():
    # 여러 서버에 걸친 상관은 광범위 장애로 보고 CRITICAL 로 올린다.
    severity = compute_severity(anomaly_count=4, server_count=3, max_deviation=2.5)
    assert severity == IncidentSeverity.CRITICAL.value


def test_large_deviation_escalates_to_critical():
    # 단일 이상이라도 편차가 매우 크면 CRITICAL.
    severity = compute_severity(anomaly_count=1, server_count=1, max_deviation=6.0)
    assert severity == IncidentSeverity.CRITICAL.value


def test_many_anomalies_escalates_to_critical():
    # 한 그룹에 이상이 다수 누적되면 CRITICAL.
    severity = compute_severity(anomaly_count=8, server_count=1, max_deviation=2.5)
    assert severity == IncidentSeverity.CRITICAL.value
