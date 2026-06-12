"""인시던트 심각도 산출 순수 로직(UC24). DB·스케줄러 비의존.

상관(correlation) 잡이 한 인시던트에 묶인 이상들의 통계를 넘겨 호출한다.
세 신호로 심각도를 정한다:
- 이상 개수(anomaly_count): 같은 인시던트에 누적된 이상이 많을수록 위험
- 관련 서버 수(server_count): 여러 서버에 걸친 상관은 광범위 장애 신호
- 최고 편차(max_deviation): 기준선에서 가장 크게 벗어난 정도(σ 배수)

학부 수준 가독성을 위해 머신러닝 없이 임계 비교만 쓴다. 임계는 명명 상수로 둔다.
"""

from app.models.enums import IncidentSeverity

# CRITICAL 로 올리는 임계(하나라도 넘으면 CRITICAL).
_CRITICAL_ANOMALY_COUNT = 5      # 한 그룹에 이상이 이만큼 쌓이면 광범위 장애로 본다
_CRITICAL_SERVER_COUNT = 2       # 둘 이상 서버에 동시 상관되면 단일 장애로 보지 않는다
_CRITICAL_DEVIATION = 5.0        # 기준선에서 5σ 넘게 벗어나면 극단 이탈

# WARNING 으로 올리는 임계(CRITICAL 이 아니면서 하나라도 넘으면 WARNING).
_WARNING_ANOMALY_COUNT = 3
_WARNING_DEVIATION = 4.0


def compute_severity(anomaly_count: int, server_count: int, max_deviation: float) -> str:
    """이상 개수·서버 수·최고 편차로 INFO/WARNING/CRITICAL 을 정한다."""
    if (
        anomaly_count >= _CRITICAL_ANOMALY_COUNT
        or server_count >= _CRITICAL_SERVER_COUNT
        or max_deviation >= _CRITICAL_DEVIATION
    ):
        return IncidentSeverity.CRITICAL.value
    if anomaly_count >= _WARNING_ANOMALY_COUNT or max_deviation >= _WARNING_DEVIATION:
        return IncidentSeverity.WARNING.value
    return IncidentSeverity.INFO.value
