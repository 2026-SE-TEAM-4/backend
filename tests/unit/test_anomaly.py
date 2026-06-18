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
    # 안정 구간은 σ 가 작아 판정용 σ 가 하한(_MIN_SIGMA=8)으로 올라간다.
    # latest=75(평균 50 에서 25 이탈)는 k=2 밴드(16) 밖이지만 k=5 밴드(40) 안이다.
    history = _stable_history()
    assert evaluate_anomaly(history, latest=75.0, k=2.0).is_anomaly is True
    assert evaluate_anomaly(history, latest=75.0, k=5.0).is_anomaly is False


def test_small_deviation_on_stable_baseline_is_not_anomaly():
    # σ 하한이 없으면 σ≈1 인 구간에서 5 만 벗어나도 이상(5 > 2.5·1)이 된다.
    # 하한(8) 덕분에 밴드가 2.5·8=20 이라, 평소 잔떨림 수준의 작은 이탈은 무시한다.
    decision = evaluate_anomaly(_stable_history(), latest=55.0)
    assert decision.is_anomaly is False


def test_drop_below_baseline_is_not_anomaly():
    # 사용량이 평균(50)보다 크게 '떨어진' 값은 장애 신호가 아니므로 이상으로 보지 않는다.
    # 위쪽 이탈만 판정하므로, 같은 폭이라도 아래로 벗어나면 비이상이다.
    decision = evaluate_anomaly(_stable_history(), latest=1.0)
    assert decision.is_anomaly is False
