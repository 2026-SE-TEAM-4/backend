"""이상탐지 순수 로직(UC18). 기준선(μ) 위쪽 이탈만 판정.

DB·스케줄러 비의존. jobs/anomaly_detection_job.py 가 최근 시계열을 넘겨 호출한다.
표준편차는 모표준편차(statistics.pstdev)를 쓴다 — 기준선 자체의 분산을 본다.

CPU·GPU·MEM·NET 은 모두 "사용량이 높아질 때"가 장애 신호다. 평균보다 낮아진 값
(사용량 감소)은 문제가 아니므로 이상으로 보지 않는다. 따라서 μ+kσ 위쪽 이탈만 본다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean, pstdev

# 기준선을 신뢰하기 위한 최소 표본 수. 미만이면 이상으로 보지 않는다.
MIN_SAMPLES = 30

# 판정에 쓰는 표준편차의 절대 하한(% 단위). 매우 안정적인 구간은 σ 가 0 에 가까워
# μ±kσ 밴드가 면도날처럼 좁아지고, 그러면 평소 잔떨림(예: GPU 합성값 ±5)조차 이상으로
# 오탐한다. 실제 측정값이 이 폭(k·_MIN_SIGMA)을 넘게 벗어나야만 이상으로 본다.
_MIN_SIGMA = 8.0


@dataclass(frozen=True)
class AnomalyDecision:
    is_anomaly: bool
    mean: float
    stddev: float


def evaluate_anomaly(
    history: Sequence[float],
    latest: float,
    *,
    min_samples: int = MIN_SAMPLES,
    k: float = 2.5,
) -> AnomalyDecision:
    """history(최신값 제외) 기준 μ+kσ 위로 벗어나면 이상으로 판정한다.

    - 표본이 min_samples 미만이면 항상 비이상(기준선 불신).
    - 표준편차가 0이면 항상 비이상(분산 없는 구간은 단정 불가).
    - 판정용 σ 에는 절대 하한(_MIN_SIGMA)을 두어, 안정 구간의 좁은 밴드 오탐을 막는다.
      반환하는 stddev 는 기록용으로 실제 σ 를 그대로 둔다.
    - 위쪽 이탈만 본다(latest - μ). 평균 아래로 떨어진 값은 이상으로 보지 않는다.
    """
    if len(history) < min_samples:
        return AnomalyDecision(False, 0.0, 0.0)

    mu = fmean(history)
    sigma = pstdev(history)
    if sigma <= 0:
        return AnomalyDecision(False, mu, sigma)

    band_sigma = max(sigma, _MIN_SIGMA)
    return AnomalyDecision(latest - mu > k * band_sigma, mu, sigma)
