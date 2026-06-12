"""메트릭 수집의 순수 로직 단위 테스트(DB·네트워크 없음).

- 서버 id → server-pool 에이전트 URL 매핑(규약: agent-N = base_port + N-1)
- /metrics 응답 페이로드 → ServerMetric 필드 파싱(gpu null 허용)
"""

import pytest

from app.services.metric_ingest import agent_metrics_url, parse_metric_payload


def test_agent_url_maps_server_id_to_agent_port():
    # server_id=1 → base_port(9101), server_id=3 → 9103
    assert agent_metrics_url("host.docker.internal", 9101, 1) == "http://host.docker.internal:9101/metrics"
    assert agent_metrics_url("host.docker.internal", 9101, 3) == "http://host.docker.internal:9103/metrics"


def test_parse_payload_maps_camel_case_to_snake_case():
    payload = {
        "serverId": 1,
        "collectedAt": "2026-06-12T09:00:00Z",
        "cpuUsage": 37.5,
        "memUsage": 61.2,
        "gpuUsage": 88.0,
        "netUsage": 12.4,
        "status": "OK",
    }
    parsed = parse_metric_payload(payload)
    assert parsed.cpu_usage == 37.5
    assert parsed.mem_usage == 61.2
    assert parsed.net_usage == 12.4
    assert parsed.gpu_usage == 88.0


def test_parse_payload_keeps_gpu_null_for_gpuless_node():
    payload = {"cpuUsage": 10.0, "memUsage": 20.0, "netUsage": 5.0, "gpuUsage": None, "status": "OK"}
    parsed = parse_metric_payload(payload)
    assert parsed.gpu_usage is None
    # cpu/mem/net은 정상값이므로 GPU가 null이어도 그대로 보존된다.
    assert parsed.cpu_usage == 10.0


def test_parse_payload_rejects_malformed_missing_required_field():
    # cpuUsage 누락 → 계약 위반. 경계에서 빠르게 실패한다.
    with pytest.raises((KeyError, ValueError)):
        parse_metric_payload({"memUsage": 20.0, "netUsage": 5.0})
