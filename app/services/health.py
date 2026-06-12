"""건강점수 산출 순수 로직(UC19). DB 비의존.

100점에서 출발해 세 축으로 감점한다:
- 고사용률(cpu/mem/gpu): 60% 초과분에 비례 감점
- 최근 24h 이상 빈도: 건당 감점(상한 있음)
- 최근 수집 누락률: 비율에 비례 감점

결과는 0~100 정수. 즉시예약 선정(reservation_service)에서 정렬 키로 쓰이므로
나쁜 서버일수록 낮은 값을 반환하는 단조성이 핵심이다.
"""

# 감점 계수(매직넘버 방지용 상수)
_USAGE_FLOOR = 60.0          # 이 사용률 이하는 감점 없음
_CPU_WEIGHT = 0.4
_MEM_WEIGHT = 0.4
_GPU_WEIGHT = 0.3
_ANOMALY_PER_EVENT = 3       # 이상 1건당 감점
_ANOMALY_CAP = 30            # 이상 감점 상한
_MISSING_WEIGHT = 20         # 누락률 1.0(=100%)일 때 감점


def _usage_penalty(usage: float, weight: float) -> float:
    return max(0.0, usage - _USAGE_FLOOR) * weight


def compute_health_score(
    *,
    cpu_usage: float,
    mem_usage: float,
    gpu_usage: float | None,
    anomaly_count_24h: int,
    missing_rate_1h: float,
) -> int:
    """현재 메트릭·이상빈도·누락률로 0~100 건강점수를 산출한다."""
    score = 100.0
    score -= _usage_penalty(cpu_usage, _CPU_WEIGHT)
    score -= _usage_penalty(mem_usage, _MEM_WEIGHT)
    if gpu_usage is not None:
        score -= _usage_penalty(gpu_usage, _GPU_WEIGHT)
    score -= min(_ANOMALY_CAP, anomaly_count_24h * _ANOMALY_PER_EVENT)
    # 다른 감점과 동일하게 raw 값으로 빼고 마지막에 한 번만 반올림한다(이중 반올림 방지).
    score -= missing_rate_1h * _MISSING_WEIGHT

    return max(0, min(100, round(score)))
