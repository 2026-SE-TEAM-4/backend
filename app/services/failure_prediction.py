"""장애·건강 열화 예측 순수 로직(UC23). DB·스케줄러 비의존.

장애 예측 잡(failure_prediction_job)이 서버별 7일 건강점수 이력·최근 이상 빈도·현재
건강점수를 넘겨 호출한다. 여기서는 다음을 결정적으로 계산한다:

- ewma_slope: 건강점수 시계열의 하루당 기울기(EWMA). 음수면 열화 중.
- classify_trend: 기울기를 IMPROVING/STABLE/DEGRADING 으로 분류(STABLE 데드밴드).
- compute_risk_score: 기울기·이상빈도·낮은 현재 건강을 가중합한 0~100 위험도.
- estimate_eta_to_risk: 열화 추세를 외삽해 위험 임계에 닿는 예상 시각.
- risk_drivers: 위험의 근거를 사람이 읽을 한국어 문구 목록으로.

순수 함수로 두는 이유: 가중치·임계가 얽힌 점수화를 잡(DB)에서 떼어내 단위 테스트로
경계·클램프를 못 박기 위함이다. 입력은 "준비된 값", 출력은 저장 가능한 숫자·시각·문구다.
"""

from datetime import datetime, timedelta

# --- 추세 분류 데드밴드 -----------------------------------------------------
# 하루당 |기울기| 가 이 값 이하이면 흔들림으로 보고 STABLE 로 둔다(미세 변동 무시).
_STABLE_DEADBAND_PER_DAY = 1.0

# --- 위험도 가중치(0~100 으로 스케일) ---------------------------------------
# 세 항을 더해 위험도를 만든다. 각 항이 단독으로도 100 을 채울 수 있게 잡아,
# 어느 한 신호만 강해도 위험이 충분히 드러나게 한다(보수적 경고). 합은 마지막에 클램프.
_SLOPE_WEIGHT = 8.0          # 하루 -1점 하락당 위험 8점(약 -12.5/일이면 이 항만으로 100)
_ANOMALY_WEIGHT = 5.0        # 최근 24h 이상 1건당 위험 5점
_LOW_HEALTH_WEIGHT = 1.0     # (100 - 현재건강) 1점당 위험 1점

# 현재 건강점수를 알 수 없을 때 쓰는 기본값(아직 산출 전이면 위험 가중을 안 준다).
_DEFAULT_HEALTH_WHEN_UNKNOWN = 100

_RISK_MIN = 0.0
_RISK_MAX = 100.0

# EWMA 평활 계수. 최근 변화에 더 민감하도록 0.5 로 둔다(학부 수준의 단순한 선택).
_EWMA_ALPHA = 0.5

# 하루를 시간으로 환산(기울기를 "하루당"으로 맞추기 위함).
_HOURS_PER_DAY = 24.0


def ewma_slope(history: list[tuple[datetime, float]] | list[float]) -> float:
    """건강점수 시계열의 하루당 기울기를 EWMA 로 추정한다(없으면 0).

    입력은 (시각, 점수) 쌍 목록(권장) 또는 점수만의 목록이다. 점수만 주어지면
    표본 간격을 모르므로 1시간 간격으로 가정한다(잡은 시각 쌍으로 호출한다).

    방법: 연속한 두 표본의 (점수차 / 시간차[일]) 를 순간 기울기로 보고, 최근값에
    가중을 더 주는 EWMA 로 누적한다. 양수면 개선, 음수면 열화. 단순·가독 우선이다.
    """
    times, scores = _split_history(history)
    if len(scores) < 2:
        return 0.0  # 표본이 한 점뿐이면 기울기를 정의할 수 없다.

    ewma: float | None = None
    for index in range(1, len(scores)):
        days = (times[index] - times[index - 1]).total_seconds() / 86400.0
        if days <= 0:
            continue  # 같은 시각·역행 표본은 기울기를 왜곡하므로 건너뛴다.
        instant_slope = (scores[index] - scores[index - 1]) / days
        if ewma is None:
            ewma = instant_slope
        else:
            ewma = _EWMA_ALPHA * instant_slope + (1 - _EWMA_ALPHA) * ewma
    return ewma if ewma is not None else 0.0


def classify_trend(slope: float) -> str:
    """하루당 기울기를 IMPROVING/STABLE/DEGRADING 으로 분류한다(데드밴드).

    |기울기| 가 데드밴드 이하이면 STABLE. 그 밖에는 부호로 가른다(양수 개선, 음수 열화).
    """
    if slope > _STABLE_DEADBAND_PER_DAY:
        return "IMPROVING"
    if slope < -_STABLE_DEADBAND_PER_DAY:
        return "DEGRADING"
    return "STABLE"


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
    history: list[tuple[datetime, float]] | list[float],
) -> tuple[list[datetime], list[float]]:
    """이력을 (시각 목록, 점수 목록)으로 가른다.

    (시각, 점수) 쌍이면 그대로 풀고, 점수만의 목록이면 1시간 간격 시각을 합성한다.
    """
    if not history:
        return [], []
    if isinstance(history[0], tuple):
        times = [point[0] for point in history]  # type: ignore[index]
        scores = [float(point[1]) for point in history]  # type: ignore[index]
        return times, scores

    # 점수만 주어진 경우: 간격을 모르므로 1시간 등간격으로 본다(테스트 편의용 경로).
    base = datetime(2026, 1, 1)
    scores = [float(value) for value in history]  # type: ignore[arg-type]
    times = [base + timedelta(hours=i) for i in range(len(scores))]
    return times, scores
