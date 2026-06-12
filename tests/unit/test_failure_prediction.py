"""장애·건강 열화 예측 순수 로직 단위 테스트(UC23). DB 없음.

7일 건강점수 이력의 기울기로 추세·위험도·위험 진입 시각·근거를 만든다.
- 하락 이력 → DEGRADING + 양의 위험 + eta 존재
- 개선/평탄 이력 → IMPROVING/STABLE + 낮은 위험 + eta None
- 위험도는 0~100 으로 클램프된다.
- 근거 문구는 실제 기여한 신호만 담는다.
"""

from datetime import datetime, timedelta, timezone

from app.services.failure_prediction import (
    classify_trend,
    compute_risk_score,
    estimate_eta_to_risk,
    ewma_slope,
    risk_drivers,
)


def _daily_history(scores: list[float]) -> list[tuple[datetime, float]]:
    # 하루 간격 (시각, 점수) 이력을 만든다(기울기를 하루당으로 보기 위함).
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return [(base + timedelta(days=i), score) for i, score in enumerate(scores)]


# --- ewma_slope ------------------------------------------------------------

def test_ewma_slope_is_negative_for_declining_history():
    # 90 → 60 으로 하루 5점씩 떨어지는 이력. 기울기는 음수(열화)여야 한다.
    slope = ewma_slope(_daily_history([90, 85, 80, 75, 70, 65, 60]))
    assert slope < 0


def test_ewma_slope_is_positive_for_rising_history():
    slope = ewma_slope(_daily_history([60, 65, 70, 75, 80, 85, 90]))
    assert slope > 0


def test_ewma_slope_is_zero_for_single_point():
    # 표본이 하나뿐이면 기울기를 정의할 수 없어 0 이다.
    assert ewma_slope(_daily_history([80])) == 0.0


def test_ewma_slope_is_zero_for_empty_history():
    assert ewma_slope([]) == 0.0


# --- classify_trend (데드밴드 포함) ----------------------------------------

def test_classify_trend_degrading_for_steep_negative_slope():
    assert classify_trend(-5.0) == "DEGRADING"


def test_classify_trend_improving_for_steep_positive_slope():
    assert classify_trend(5.0) == "IMPROVING"


def test_classify_trend_stable_inside_deadband():
    # 데드밴드(±1.0/일) 안의 미세 흔들림은 STABLE 로 본다.
    assert classify_trend(0.5) == "STABLE"
    assert classify_trend(-0.5) == "STABLE"
    assert classify_trend(0.0) == "STABLE"


# --- compute_risk_score (클램프 + 각 항) -----------------------------------

def test_risk_score_rises_with_steeper_decline():
    gentle = compute_risk_score(health_slope=-1.0, anomaly_count_24h=0, current_health=90)
    steep = compute_risk_score(health_slope=-5.0, anomaly_count_24h=0, current_health=90)
    assert steep > gentle


def test_risk_score_rises_with_more_anomalies():
    few = compute_risk_score(health_slope=0.0, anomaly_count_24h=1, current_health=90)
    many = compute_risk_score(health_slope=0.0, anomaly_count_24h=9, current_health=90)
    assert many > few


def test_risk_score_rises_when_current_health_is_low():
    healthy = compute_risk_score(health_slope=0.0, anomaly_count_24h=0, current_health=90)
    sick = compute_risk_score(health_slope=0.0, anomaly_count_24h=0, current_health=20)
    assert sick > healthy


def test_risk_score_improving_trend_does_not_add_risk():
    # 개선(양의 기울기)은 위험을 더하지 않는다. 다른 신호가 없으면 위험은 0 이다.
    risk = compute_risk_score(health_slope=10.0, anomaly_count_24h=0, current_health=100)
    assert risk == 0.0


def test_risk_score_is_clamped_to_0_100():
    # 모든 신호가 극단이어도 100 을 넘지 않는다.
    risk = compute_risk_score(health_slope=-100.0, anomaly_count_24h=100, current_health=0)
    assert 0.0 <= risk <= 100.0
    assert risk == 100.0


def test_risk_score_unknown_health_defaults_to_no_low_health_penalty():
    # 현재 건강을 모르면(아직 산출 전) 낮은 건강 가중을 주지 않는다(다른 신호 없으면 0).
    risk = compute_risk_score(health_slope=0.0, anomaly_count_24h=0, current_health=None)
    assert risk == 0.0


# --- estimate_eta_to_risk --------------------------------------------------

def test_eta_is_returned_for_degrading_server():
    # 현재 80, 하루 -5 점 → 위험(50)까지 6일 뒤로 외삽된다.
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    eta = estimate_eta_to_risk(now=now, current_health=80, health_slope=-5.0, danger_health=50)
    assert eta is not None
    assert eta == now + timedelta(days=6)


def test_eta_is_none_for_improving_server():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    eta = estimate_eta_to_risk(now=now, current_health=80, health_slope=3.0, danger_health=50)
    assert eta is None


def test_eta_is_none_when_already_below_danger():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    eta = estimate_eta_to_risk(now=now, current_health=40, health_slope=-5.0, danger_health=50)
    assert eta is None


def test_eta_is_none_when_health_unknown():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    eta = estimate_eta_to_risk(now=now, current_health=None, health_slope=-5.0, danger_health=50)
    assert eta is None


# --- risk_drivers ----------------------------------------------------------

def test_drivers_describe_active_signals():
    drivers = risk_drivers(health_slope=-4.1, anomaly_count_24h=9, current_health=30)
    assert any("기울기" in driver for driver in drivers)
    assert any("이상" in driver for driver in drivers)
    assert any("health" in driver for driver in drivers)


def test_drivers_empty_for_healthy_stable_server():
    # 개선 중이고 이상도 없고 건강도 만점이면 위험 근거가 없다.
    drivers = risk_drivers(health_slope=2.0, anomaly_count_24h=0, current_health=100)
    assert drivers == []
