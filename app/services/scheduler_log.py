"""스케줄러 실행 로그 적재 헬퍼(UC21 F21).

대시보드(F21)가 잡 실행 이력을 보여주기 위해 각 잡이 성공 실행 시 한 행을 남긴다.
잡마다 같은 코드를 반복하지 않도록 한 줄짜리 적재 함수로 모은다.
"""

from app.models import SchedulerLog


def add_scheduler_log(
    db, uc_id: str, processed_count: int, success: bool = True
) -> None:
    """이번 실행을 SchedulerLog 한 행으로 세션에 추가한다(commit 은 잡이 한다).

    executed_at 은 모델의 server_default(now())가 채우므로 여기서 넘기지 않는다.
    """
    db.add(SchedulerLog(uc_id=uc_id, success=success, processed_count=processed_count))
