"""용량·수요 예측 순수 로직 단위 테스트(UC22). DB 없음.

준비된 시간색인 pandas.Series 를 받아 Holt-Winters 로 향후 구간을 예측한다.
- 뚜렷이 상승하는 시계열 → 포화 임계를 넘는 saturation_at 이 나온다.
- 낮고 평평한 시계열 → 끝까지 임계를 넘지 않아 saturation_at 은 None 이다.
- first_saturation 은 임계를 처음 넘는 시점을 경계 포함(>=)으로 고른다.
- 표본이 최소치 미만이면 명확한 ValueError 로 거른다(잡이 건너뛸 신호).
"""

import pandas as pd
import pytest

from app.services.forecast import (
    MIN_SAMPLES,
    InsufficientHistoryError,
    first_saturation,
    forecast_series,
)


def _hourly_series(values: list[float]) -> pd.Series:
    # 1시간 간격 시간색인 시계열을 만든다(예측 함수가 기대하는 입력 형태).
    index = pd.date_range("2026-01-01", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=index, dtype=float)


def test_rising_series_produces_saturation_at():
    # 40 → 95 로 꾸준히 오르는 사용률. 예측 구간 안에서 90 임계를 넘어야 한다.
    rising = [40.0 + i * (55.0 / (MIN_SAMPLES * 2)) for i in range(MIN_SAMPLES * 2)]
    result = forecast_series(_hourly_series(rising), horizon_hours=72, threshold=90.0)

    assert result.saturation_at is not None
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.horizon) == 72
    # 각 예측점은 ts/yhat/lower/upper 를 가지며 밴드는 lower<=yhat<=upper 다.
    first = result.horizon[0]
    assert set(first) == {"ts", "yhat", "lower", "upper"}
    assert first["lower"] <= first["yhat"] <= first["upper"]


def test_flat_low_series_has_no_saturation():
    # 낮은 수준에서 미세하게 흔들리는 평탄 시계열. 임계(90)에 닿지 않는다.
    flat = [20.0 + (1 if i % 2 else -1) for i in range(MIN_SAMPLES * 2)]
    result = forecast_series(_hourly_series(flat), horizon_hours=72, threshold=90.0)

    assert result.saturation_at is None


def test_short_series_raises_insufficient_history():
    # 최소 표본 미만이면 적합을 시도하지 않고 명확히 거른다.
    with pytest.raises(InsufficientHistoryError):
        forecast_series(_hourly_series([50.0] * (MIN_SAMPLES - 1)))


def test_first_saturation_returns_first_crossing_ts():
    horizon = [
        {"ts": "2026-01-01T00:00:00+00:00", "yhat": 80.0, "lower": 70.0, "upper": 90.0},
        {"ts": "2026-01-01T01:00:00+00:00", "yhat": 90.0, "lower": 80.0, "upper": 100.0},
        {"ts": "2026-01-01T02:00:00+00:00", "yhat": 95.0, "lower": 85.0, "upper": 105.0},
    ]
    # 경계 포함(>=)이라 정확히 90 인 두 번째 점이 첫 포화 시각이다.
    assert first_saturation(horizon, threshold=90.0) == "2026-01-01T01:00:00+00:00"


def test_first_saturation_returns_none_when_never_crossing():
    horizon = [
        {"ts": "2026-01-01T00:00:00+00:00", "yhat": 50.0, "lower": 40.0, "upper": 60.0},
        {"ts": "2026-01-01T01:00:00+00:00", "yhat": 55.0, "lower": 45.0, "upper": 65.0},
    ]
    assert first_saturation(horizon, threshold=90.0) is None
