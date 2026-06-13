"""장애·건강 열화 예측 순수 로직(UC23). DB·스케줄러 비의존.

장애 예측 잡(failure_prediction_job)이 서버별 7일 건강점수 이력·최근 이상 빈도·현재
건강점수를 넘겨 호출한다. 여기서는 다음을 결정적으로 계산한다:

- health_slope_per_day: 건강점수 시계열의 하루당 기울기(최소제곱). 음수면 열화 중.
- classify_trend: 기울기를 IMPROVING/STABLE/DEGRADING 으로 분류(STABLE 데드밴드).
- compute_risk_score: 기울기·이상빈도·낮은 현재 건강을 가중합한 0~100 위험도.
- estimate_eta_to_risk: 열화 추세를 외삽해 위험 임계에 닿는 예상 시각.
- risk_drivers: 위험의 근거를 사람이 읽을 한국어 문구 목록으로.

순수 함수로 두는 이유: 가중치·임계가 얽힌 점수화를 잡(DB)에서 떼어내 단위 테스트로
경계·클램프를 못 박기 위함이다. 입력은 "준비된 값", 출력은 저장 가능한 숫자·시각·문구다.
"""

from datetime import datetime, timedelta
from statistics import fmean

from app.models.enums import TrendDirection

# --- 추세 분류 데드밴드 -----------------------------------------------------
# 하루당 |기울기| 가 이 값 이하이면 흔들림으로 보고 STABLE 로 둔다(미세 변동 무시).
_STABLE_DEADBAND_PER_DAY = 1.0

# --- 위험도 가중치(0~100 으로 스케일) ---------------------------------------
# 세 항을 더해 위험도를 만든다. 합은 마지막에 클램프.
#
# 이 시스템은 보통 몇 시간만 돌린다. '며칠에 걸친 하락 추세'는 그 시간 안에 거의
# 측정되지 않으므로, 위험도는 측정 가능한 현재 상태(현재 건강·최근 이상)를 주신호로
# 삼고 기울기는 보조 신호로만 쓴다. 기울기 항이 단독으로 위험을 포화시키지 못하도록,
# 기울기는 health_slope_per_day 에서 ±_MAX_ABS_SLOPE 로 제한된 뒤 가중된다.
_SLOPE_WEIGHT = 1.0          # 하루 -1점 하락당 위험 1점(최대 하락 -20/일이면 20점)
_ANOMALY_WEIGHT = 1.5        # 최근 24h 이상 1건당 위험 1.5점(20건 = 30점)
_LOW_HEALTH_WEIGHT = 1.0     # (100 - 현재건강) 1점당 위험 1점

# 현재 건강점수를 알 수 없을 때 쓰는 기본값(아직 산출 전이면 위험 가중을 안 준다).
_DEFAULT_HEALTH_WHEN_UNKNOWN = 100

_RISK_MIN = 0.0
_RISK_MAX = 100.0

# 기울기를 신뢰하려면 최소 이만큼의 표본이 필요하다. 미만이면 추세 0(판정 보류).
_MIN_POINTS = 3
# 하루당 기울기의 절대 상한. 10분 간격 표본의 작은 흔들림을 하루로 외삽하면 수백/일로
# 부풀려지므로, 물리적으로 의미 있는 범위(건강 100→0 을 5일에 걸치는 -20/일 수준)로
# 제한한다. 노이즈가 위험도를 포화시키는 것을 막는 안전장치다.
_MAX_ABS_SLOPE = 20.0

# 초를 일로 환산(기울기를 "하루당"으로 맞추기 위함).
_SECONDS_PER_DAY = 86400.0


def health_slope_per_day(history: list[tuple[datetime, float]]) -> float:
    """건강점수 시계열의 하루당 변화 기울기를 최소제곱 직선으로 추정한다(없으면 0).

    입력은 (시각, 점수) 쌍의 시간순 목록이다. 양수면 개선, 음수면 열화.

    최소제곱을 쓰는 이유: 표본 하나하나(예: 10분 간격)의 차이를 그대로 하루로
    외삽하면 미세한 흔들림이 큰 기울기로 부풀려진다. 직선 적합은 전체 구간에 걸쳐
    흔들림을 평균내어 '지속적인' 추세만 남긴다. 결과는 ±_MAX_ABS_SLOPE 로 제한한다.
    """
    times, scores = _split_history(history)
    if len(scores) < _MIN_POINTS:
        return 0.0  # 표본이 적으면 추세를 신뢰할 수 없다.

    base = times[0]
    days = [(point_time - base).total_seconds() / _SECONDS_PER_DAY for point_time in times]
    mean_x = fmean(days)
    mean_y = fmean(scores)
    denom = sum((x - mean_x) ** 2 for x in days)
    if denom <= 0:
        return 0.0  # 모든 시각이 같으면 기울기를 정의할 수 없다.

    numer = sum((x - mean_x) * (y - mean_y) for x, y in zip(days, scores))
    slope = numer / denom
    return max(-_MAX_ABS_SLOPE, min(_MAX_ABS_SLOPE, slope))


def classify_trend(slope: float) -> str:
    """하루당 기울기를 IMPROVING/STABLE/DEGRADING 으로 분류한다(데드밴드).

    |기울기| 가 데드밴드 이하이면 STABLE. 그 밖에는 부호로 가른다(양수 개선, 음수 열화).
    """
    if slope > _STABLE_DEADBAND_PER_DAY:
        return TrendDirection.IMPROVING.value
    if slope < -_STABLE_DEADBAND_PER_DAY:
        return TrendDirection.DEGRADING.value
    return TrendDirection.STABLE.value


def compute_risk_score(
    *,
    health_slope: float,
    anomaly_count_24h: int,
    current_health: int | None,
) -> float:
    """기울기·이상빈도·낮은 현재 건강을 가중합한 0~100 위험도를 만든다.

    - 하락(음의 기울기)만 위험으로 본다(개선은 위험을 더하지 않는다).
    - 이상 빈도가 높을수록 위험이 오른다.
    - 현재 건강이 낮을수록 위험이 오른다((100 - 건강) 만큼).
    합이 0~100 을 벗어나면 클램프한다.
    """
    health = current_health if current_health is not None else _DEFAULT_HEALTH_WHEN_UNKNOWN
    degradation = max(0.0, -health_slope)  # 하락분만 양수로 취한다.
    low_health = max(0, _DEFAULT_HEALTH_WHEN_UNKNOWN - health)

    risk = (
        _SLOPE_WEIGHT * degradation
        + _ANOMALY_WEIGHT * anomaly_count_24h
        + _LOW_HEALTH_WEIGHT * low_health
    )
    return max(_RISK_MIN, min(_RISK_MAX, risk))


def estimate_eta_to_risk(
    *,
    now: datetime,
    current_health: int | None,
    health_slope: float,
    danger_health: int,
) -> datetime | None:
    """열화 추세를 외삽해 건강점수가 위험 임계에 닿는 예상 시각을 만든다(없으면 None).

    - 현재 건강을 모르거나 이미 임계 이하이면 None(예측할 위험 진입 시점이 없다).
    - 안정·개선(기울기 >= 0)이면 None(임계로 내려가지 않는다).
    - 열화 중이면 (현재건강 - 임계) / 일당하락분 만큼의 날 뒤를 예상 시각으로 본다.
    """
    if current_health is None or current_health <= danger_health:
        return None
    if health_slope >= 0:
        return None  # 하락하지 않으면 임계에 닿지 않는다.

    drop_per_day = -health_slope  # 양수(하루당 떨어지는 점수)
    days_until_danger = (current_health - danger_health) / drop_per_day
    return now + timedelta(days=days_until_danger)


def risk_drivers(
    *,
    health_slope: float,
    anomaly_count_24h: int,
    current_health: int | None,
) -> list[str]:
    """위험의 근거를 사람이 읽을 한국어 문구 목록으로 만든다(해당 항목만).

    각 신호가 실제로 위험에 기여할 때만 문구를 넣는다. 운영자가 알림에서 곧바로
    "왜 위험한가"를 읽을 수 있게 하기 위함이다.
    """
    drivers: list[str] = []
    if health_slope < 0:
        drivers.append(f"health 기울기 {health_slope:.1f}/일")
    if anomaly_count_24h > 0:
        drivers.append(f"최근 24h 이상 {anomaly_count_24h}건")
    if current_health is not None and current_health < _DEFAULT_HEALTH_WHEN_UNKNOWN:
        drivers.append(f"현재 health {current_health}점")
    return drivers


def _split_history(
    history: list[tuple[datetime, float]],
) -> tuple[list[datetime], list[float]]:
    """(시각, 점수) 쌍 목록을 (시각 목록, 점수 목록)으로 가른다."""
    times = [point[0] for point in history]
    scores = [float(point[1]) for point in history]
    return times, scores
