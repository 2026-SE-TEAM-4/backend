"""이상탐지 순수 로직 단위 테스트(μ±2σ). DB 없음.

과거값(history) 기준 평균·표준편차를 구해 최신값(latest)이 ±kσ 밖이면 이상으로 본다.
표본이 부족하거나 표준편차가 0이면 이상으로 보지 않는다(오탐 방지).
"""

from app.services.anomaly import evaluate_anomaly


def _stable_history(value: float = 50.0, n: int = 60) -> list[float]:
    # 약간의 분산이 있는 안정 구간(σ>0)을 만든다.
    return [value + (1 if i % 2 else -1) for i in range(n)]


def test_normal_value_within_band_is_not_anomaly():
    decision = evaluate_anomaly(_stable_history(), latest=50.5)
    assert decision.is_anomaly is False
    assert decision.stddev > 0


def test_extreme_outlier_is_anomaly():
    decision = evaluate_anomaly(_stable_history(), latest=99.0)
    assert decision.is_anomaly is True
    assert decision.mean == 50.0  # ±1 대칭이라 평균 50


def test_insufficient_samples_is_never_anomaly():
    # 표본 30개 미만이면 기준선을 신뢰할 수 없어 이상으로 보지 않는다.
    decision = evaluate_anomaly([50.0] * 10, latest=99.0)
    assert decision.is_anomaly is False


def test_zero_variance_history_is_never_anomaly():
    # 완전히 동일한 과거값(σ=0)에서는 어떤 값도 이상으로 단정하지 않는다.
    decision = evaluate_anomaly([50.0] * 60, latest=99.0)
    assert decision.is_anomaly is False
    assert decision.stddev == 0.0


def test_custom_k_widens_band():
    history = _stable_history()  # σ ≈ 1
    # latest=53 은 2σ 밖이지만 k=5 밴드 안이다.
    assert evaluate_anomaly(history, latest=53.0, k=2.0).is_anomaly is True
    assert evaluate_anomaly(history, latest=53.0, k=5.0).is_anomaly is False
