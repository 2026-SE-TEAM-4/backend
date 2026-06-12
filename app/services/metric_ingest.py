"""메트릭 수집의 순수 로직(DB·네트워크 비의존).

server-pool 에이전트 엔드포인트 매핑과 /metrics 페이로드 파싱만 담당한다.
실제 HTTP 호출·DB 적재는 jobs/metric_collection_job.py 가 이 함수들을 조립해 수행한다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedMetric:
    """/metrics 응답을 ServerMetric 컬럼명으로 변환한 결과."""

    cpu_usage: float
    mem_usage: float
    net_usage: float
    gpu_usage: float | None  # GPU 미탑재 노드는 None(상태는 항상 OK로 본다)


def agent_metrics_url(host: str, base_port: int, server_id: int) -> str:
    """서버 id를 server-pool 에이전트 /metrics URL로 매핑한다.

    규약(MVP): agent-N 컨테이너는 base_port + (N-1) 포트를 쓴다(server_id=1 → base_port).
    실서버 확장 시에는 서버별 엔드포인트 저장 방식으로 교체한다.
    """
    return f"http://{host}:{base_port + server_id - 1}/metrics"


def parse_metric_payload(payload: dict) -> ParsedMetric:
    """에이전트 응답(camelCase)을 ParsedMetric(snake_case)으로 변환한다.

    cpu/mem/net 은 필수다. 누락 시 KeyError로 경계에서 즉시 실패한다.
    gpuUsage 가 null이면 해당 노드는 GPU 미탑재로 보고 gpu_usage=None 으로 둔다
    (행 status는 수집기가 OK로 기록 — cpu/mem/net 분석을 막지 않기 위함).
    """
    gpu = payload.get("gpuUsage")
    return ParsedMetric(
        cpu_usage=float(payload["cpuUsage"]),
        mem_usage=float(payload["memUsage"]),
        net_usage=float(payload["netUsage"]),
        gpu_usage=None if gpu is None else float(gpu),
    )
