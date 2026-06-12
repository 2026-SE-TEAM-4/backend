"""유휴 서버 판정 순수 로직(F24/UC15). DB·스케줄러 비의존.

회수 잡(idle_reclaim_job)이 서버별 최근 평균 CPU 사용률을 넘겨 호출한다.
유휴 판정과 시간 임계를 한 곳에 모아 단위 테스트가 가능하게 한다.
학부 수준 가독성을 위해 머신러닝 없이 임계 비교만 쓴다. 임계는 명명 상수로 둔다.
"""

from datetime import timedelta

# 최근 이 구간의 평균 CPU 사용률로 유휴 여부를 본다.
IDLE_LOOKBACK = timedelta(minutes=30)
# 이 값 미만이면 유휴(저사용률)로 본다. 단위는 % (메트릭 cpu_usage 와 동일).
IDLE_CPU_THRESHOLD = 5.0
# IDLE_WARNING 발송 후 이만큼 더 유휴가 지속되면 회수한다(2단계 경고).
RECLAIM_GRACE = timedelta(minutes=15)


def is_idle(avg_cpu_usage: float | None) -> bool:
    """최근 평균 CPU 사용률이 유휴 임계 미만인지 판정한다.

    측정값이 없으면(None) 유휴로 단정하지 않는다. 회수는 점유 해제라 되돌리기
    어려우므로, 근거가 없을 때는 보수적으로 유휴가 아니라고 본다.
    """
    if avg_cpu_usage is None:
        return False
    return avg_cpu_usage < IDLE_CPU_THRESHOLD
