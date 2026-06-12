"""건강점수 순수 로직 단위 테스트(UC19). DB 없음.

100점에서 출발해 고사용률·이상빈도·수집누락을 감점한다. 결과는 0~100 정수.
절대값보다 단조성(나쁠수록 낮음)이 중요하다 — 즉시예약 선정 정렬에 쓰인다.
"""

from app.services.health import compute_health_score


def test_idle_server_scores_full():
    score = compute_health_score(
        cpu_usage=10.0, mem_usage=20.0, gpu_usage=None,
        anomaly_count_24h=0, missing_rate_1h=0.0,
    )
    assert score == 100


def test_high_cpu_and_mem_lowers_score():
    score = compute_health_score(
        cpu_usage=100.0, mem_usage=100.0, gpu_usage=None,
        anomaly_count_24h=0, missing_rate_1h=0.0,
    )
    # cpu/mem 각각 max(0,100-60)*0.4 = 16 감점 → 100 - 32
    assert score == 68


def test_anomalies_lower_score_with_cap():
    score = compute_health_score(
        cpu_usage=10.0, mem_usage=10.0, gpu_usage=None,
        anomaly_count_24h=5, missing_rate_1h=0.0,
    )
    assert score == 85  # min(30, 5*3) = 15 감점


def test_missing_rate_lowers_score():
    score = compute_health_score(
        cpu_usage=10.0, mem_usage=10.0, gpu_usage=None,
        anomaly_count_24h=0, missing_rate_1h=0.5,
    )
    assert score == 90  # round(0.5*20) = 10 감점


def test_gpu_usage_penalized_when_present():
    score = compute_health_score(
        cpu_usage=10.0, mem_usage=10.0, gpu_usage=100.0,
        anomaly_count_24h=0, missing_rate_1h=0.0,
    )
    assert score == 88  # max(0,100-60)*0.3 = 12 감점


def test_score_is_clamped_to_zero_floor():
    score = compute_health_score(
        cpu_usage=100.0, mem_usage=100.0, gpu_usage=100.0,
        anomaly_count_24h=100, missing_rate_1h=1.0,
    )
    assert 0 <= score <= 100


def test_worse_server_scores_lower_than_better_server():
    healthy = compute_health_score(
        cpu_usage=30.0, mem_usage=30.0, gpu_usage=None,
        anomaly_count_24h=0, missing_rate_1h=0.0,
    )
    degraded = compute_health_score(
        cpu_usage=95.0, mem_usage=90.0, gpu_usage=None,
        anomaly_count_24h=8, missing_rate_1h=0.2,
    )
    assert degraded < healthy
