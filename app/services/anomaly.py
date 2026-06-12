"""이상탐지 순수 로직(UC18). μ±kσ 기준선 이탈 판정.

DB·스케줄러 비의존. jobs/anomaly_detection_job.py 가 최근 시계열을 넘겨 호출한다.
표준편차는 모표준편차(statistics.pstdev)를 쓴다 — 기준선 자체의 분산을 본다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean, pstdev

# 기준선을 신뢰하기 위한 최소 표본 수. 미만이면 이상으로 보지 않는다.
MIN_SAMPLES = 30


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
    k: float = 2.0,
) -> AnomalyDecision:
    """history(최신값 제외) 기준 μ±kσ 밖이면 이상으로 판정한다.

    - 표본이 min_samples 미만이면 항상 비이상(기준선 불신).
    - 표준편차가 0이면 항상 비이상(분산 없는 구간은 단정 불가).
    """
    if len(history) < min_samples:
        return AnomalyDecision(False, 0.0, 0.0)

    mu = fmean(history)
    sigma = pstdev(history)
    if sigma <= 0:
        return AnomalyDecision(False, mu, sigma)

    return AnomalyDecision(abs(latest - mu) > k * sigma, mu, sigma)
