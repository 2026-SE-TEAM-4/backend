"""용량·수요 예측 순수 로직(UC22). DB·스케줄러 비의존.

예측 잡(forecast_job)이 1시간 간격으로 리샘플·보간한 시계열(pandas.Series)을 넘겨 호출한다.
Holt-Winters 지수평활(statsmodels)로 향후 N시간을 예측하고, 잔차 표준편차로 신뢰구간을 만든다.

순수 함수로 두는 이유: statsmodels 적합을 잡(DB·네트워크)에서 떼어내 결정적으로 단위
테스트하기 위함이다. 입력은 "준비된 시계열", 출력은 저장 가능한 예측점 목록이다.
"""

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.holtwinters import ExponentialSmoothing

# 적합을 신뢰하기 위한 최소 표본 수(시간 단위). 미만이면 예측을 시도하지 않는다.
# 학기 단위 데이터로도 테스트·운영이 가능하도록 이틀치(48시간)로 둔다.
MIN_SAMPLES = 48

# 일 주기(24시간) 계절성을 쓰려면 최소 2개 시즌이 필요하다(statsmodels 요구).
_SEASONAL_PERIODS = 24
_MIN_SEASONS_FOR_SEASONAL = 2

# 기본 예측 구간(7일)과 기본 포화 임계(사용률 %).
_DEFAULT_HORIZON_HOURS = 168
_DEFAULT_THRESHOLD = 90.0

# 신뢰구간 폭(95%)에 쓰는 정규분포 계수.
_CONFIDENCE_Z = 1.96


class InsufficientHistoryError(ValueError):
    """표본이 MIN_SAMPLES 미만이라 예측을 만들 수 없을 때 던진다(잡이 건너뛸 신호)."""


@dataclass(frozen=True)
class ForecastResult:
    """예측 한 건의 결과. Forecast 모델에 그대로 저장할 수 있는 형태."""

    horizon: list[dict]  # [{ts, yhat, lower, upper}], ts 는 ISO 문자열
    confidence: float  # 0..1, 잔차가 작을수록 1 에 가깝다
    saturation_at: str | None  # 임계를 처음 넘는 ts(ISO), 없으면 None


def forecast_series(
    series: pd.Series,
    *,
    horizon_hours: int = _DEFAULT_HORIZON_HOURS,
    threshold: float = _DEFAULT_THRESHOLD,
) -> ForecastResult:
    """시간색인 시계열을 받아 향후 horizon_hours 시간을 예측한다.

    - 표본이 MIN_SAMPLES 미만이면 InsufficientHistoryError.
    - 2개 시즌(48시간) 이상이면 일 주기 가산 계절성을, 아니면 비계절 모형을 쓴다.
    - 신뢰구간은 잔차 표준편차로 yhat ± 1.96·resid_std.
    - saturation_at 은 yhat 이 threshold 를 처음 넘는 시각(없으면 None).
    """
    if len(series) < MIN_SAMPLES:
        raise InsufficientHistoryError(
            f"예측에 필요한 최소 표본({MIN_SAMPLES})보다 적습니다: {len(series)}"
        )

    # 선두에 빈 버킷이 있으면 interpolate() 가 backfill 하지 못해 NaN 이 남는다.
    # NaN 을 그대로 적합하면 전 구간 yhat 이 NaN 이 되고 confidence=1.0 인 잘못된
    # 행이 저장되며 JSON 직렬화도 깨진다. 적합 전에 fail-fast 로 막는다.
    if series.isna().any():
        raise InsufficientHistoryError("준비된 시계열에 결측(NaN)이 남아 예측할 수 없습니다.")

    fitted = _fit(series)
    forecast_values = fitted.forecast(horizon_hours)
    resid_std = _residual_std(fitted)
    band = _CONFIDENCE_Z * resid_std

    horizon = _to_points(forecast_values, band)
    return ForecastResult(
        horizon=horizon,
        confidence=_confidence_from_resid(series, resid_std),
        saturation_at=first_saturation(horizon, threshold),
    )


def first_saturation(horizon: Sequence[dict], threshold: float) -> str | None:
    """horizon 에서 yhat 이 threshold 를 처음으로 넘는(>=) 시점의 ts 를 반환한다.

    경계를 포함(>=)하는 이유: 임계에 정확히 도달한 시점도 포화로 본다(보수적 경고).
    """
    for point in horizon:
        if point["yhat"] >= threshold:
            return point["ts"]
    return None


def _fit(series: pd.Series) -> ExponentialSmoothing:
    """가산 추세 Holt-Winters 를 적합한다. 데이터가 충분하면 일 주기 계절성을 더한다.

    statsmodels 는 표본이 빈약하면 ConvergenceWarning 을 내지만 결과는 사용 가능하다.
    경고가 로그를 더럽히지 않도록 적합 동안만 억제한다(예측 자체는 막지 않는다).
    """
    has_two_seasons = len(series) >= _SEASONAL_PERIODS * _MIN_SEASONS_FOR_SEASONAL
    seasonal = "add" if has_two_seasons else None
    seasonal_periods = _SEASONAL_PERIODS if has_two_seasons else None

    model = ExponentialSmoothing(
        series,
        trend="add",
        seasonal=seasonal,
        seasonal_periods=seasonal_periods,
        initialization_method="estimated",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        return model.fit()


def _residual_std(fitted: ExponentialSmoothing) -> float:
    """적합 잔차의 표준편차. 잔차가 비어 있거나 NaN 이면 0 으로 본다(밴드 폭 0)."""
    resid = np.asarray(fitted.resid, dtype=float)
    resid = resid[~np.isnan(resid)]
    if resid.size == 0:
        return 0.0
    return float(np.std(resid))


def _confidence_from_resid(series: pd.Series, resid_std: float) -> float:
    """잔차 표준편차를 시계열 규모로 정규화해 0..1 신뢰도로 만든다.

    잔차가 작을수록(예측이 과거를 잘 따라갈수록) 1 에 가깝다. 단순·가독 우선으로
    confidence = 1 / (1 + resid_std/scale) 를 쓴다. scale 은 시계열 평균 크기로 둔다.
    """
    scale = float(np.mean(np.abs(series.to_numpy(dtype=float))))
    if scale <= 0:
        return 0.0
    # 이 값은 적합이 과거를 얼마나 잘 따라갔는지를 보는 in-sample 품질 지표(0..1)다.
    # 확률적 신뢰구간이 아니며, 미래 예측의 불확실성을 직접 보장하지는 않는다.
    return round(1.0 / (1.0 + resid_std / scale), 4)


def _to_points(forecast_values: pd.Series, band: float) -> list[dict]:
    """예측 시계열을 [{ts, yhat, lower, upper}] 목록으로 바꾼다. ts 는 ISO 문자열."""
    points = []
    for ts, yhat in forecast_values.items():
        value = float(yhat)
        points.append({
            "ts": ts.isoformat(),
            "yhat": value,
            "lower": value - band,
            "upper": value + band,
        })
    return points
