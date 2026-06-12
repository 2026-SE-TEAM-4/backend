"""LLM 원인 요약 순수 로직 단위 테스트(UC25). DB·네트워크 없음.

요약 잡(incident_summary_job)이 이미 조회한 평문 데이터를 넘겨 호출한다.
- build_prompt 는 운영 데이터와 "데이터에 없으면 추측 금지" 지시를 포함해야 한다.
- parse_summary 는 모델이 돌려준 JSON 텍스트를 필드로 풀고, 형식이 깨지면 명확히 거른다.

순수 함수로 두는 이유: Gemini 호출(네트워크)을 잡에서 떼어내 결정적으로 단위
테스트하기 위함이다. 입력은 "준비된 평문 데이터", 출력은 프롬프트 문자열과 파싱 결과다.
"""

import json

import pytest

from app.services.incident_summary import (
    ParsedSummary,
    SummaryParseError,
    build_context,
    build_prompt,
    parse_summary,
)


def _sample_context() -> dict:
    # build_context 가 만드는 형태와 동일한 평문 dict(프롬프트 입력).
    return {
        "incident": {"id": 7, "severity": "WARNING", "status": "OPEN",
                     "serverIds": [1, 2]},
        "anomalies": [
            {"serverId": 1, "metric": "CPU", "currentValue": 99.0,
             "mean": 50.0, "stddev": 10.0, "detectedAt": "2026-06-12T00:00:00+00:00"},
        ],
        "servers": [{"id": 1, "name": "s1", "groupName": "lab"}],
        "serverMetrics": [
            {"serverId": 1, "cpuUsage": 99.0, "memUsage": 30.0,
             "collectedAt": "2026-06-12T00:00:00+00:00"},
        ],
    }


def test_build_context_structures_plain_data():
    incident = {"id": 7, "severity": "WARNING", "status": "OPEN", "server_ids": [1, 2]}
    anomalies = [
        {"server_id": 1, "metric": "CPU", "current_value": 99.0, "mean": 50.0,
         "stddev": 10.0, "detected_at": "2026-06-12T00:00:00+00:00"},
    ]
    server_metrics = [
        {"server_id": 1, "cpu_usage": 99.0, "mem_usage": 30.0,
         "collected_at": "2026-06-12T00:00:00+00:00"},
    ]
    servers = [{"id": 1, "name": "s1", "group_name": "lab"}]

    context = build_context(incident, anomalies, server_metrics, servers)

    # 컨텍스트는 JSON 직렬화 가능해야 한다(프롬프트에 그대로 실린다).
    json.dumps(context)
    assert context["incident"]["id"] == 7
    assert context["anomalies"][0]["serverId"] == 1
    assert context["servers"][0]["name"] == "s1"
    assert context["serverMetrics"][0]["cpuUsage"] == 99.0


def test_build_prompt_includes_data_and_no_hallucination_instruction():
    prompt = build_prompt(_sample_context())

    # 프롬프트에 실제 운영 데이터(서버/값)가 들어가야 한다.
    assert "99.0" in prompt or "99" in prompt
    assert "CPU" in prompt
    # 환각 억제 지시(데이터에 없으면 추측 금지)가 들어가야 한다.
    assert "추측" in prompt
    # 한국어로 ①상황 ②원인 후보 ③권장 조치를 요구해야 한다.
    assert "상황" in prompt
    assert "원인" in prompt
    assert "권장" in prompt
    # STRICT JSON 키를 명시해야 한다.
    assert "situation" in prompt
    assert "rootCauses" in prompt
    assert "recommendations" in prompt


def test_parse_summary_valid_json_returns_fields():
    response_text = json.dumps({
        "situation": "서버 1의 CPU 사용률이 평균을 크게 초과했습니다.",
        "rootCauses": [
            {"cause": "CPU 과부하", "evidence": "서버 1 CPU 99% (2026-06-12T00:00:00)"},
        ],
        "recommendations": [
            {"action": "부하 분산", "rationale": "단일 서버 포화를 완화하기 위함"},
        ],
    })

    parsed = parse_summary(response_text)

    assert isinstance(parsed, ParsedSummary)
    assert parsed.situation.startswith("서버 1")
    assert parsed.root_causes[0]["cause"] == "CPU 과부하"
    assert parsed.recommendations[0]["action"] == "부하 분산"


def test_parse_summary_tolerates_code_fence_wrapping():
    # 모델이 ```json ... ``` 코드펜스로 감싸 보내도 파싱해야 한다(흔한 출력 형태).
    inner = {
        "situation": "상황 요약",
        "rootCauses": [{"cause": "원인", "evidence": "근거"}],
        "recommendations": [{"action": "조치", "rationale": "이유"}],
    }
    response_text = "```json\n" + json.dumps(inner) + "\n```"

    parsed = parse_summary(response_text)

    assert parsed.situation == "상황 요약"


def test_parse_summary_malformed_json_raises():
    with pytest.raises(SummaryParseError):
        parse_summary("이건 JSON 이 아닙니다.")


def test_parse_summary_missing_keys_raises():
    # situation 만 있고 rootCauses/recommendations 가 없으면 형식 위반으로 거른다.
    with pytest.raises(SummaryParseError):
        parse_summary(json.dumps({"situation": "상황만 있음"}))


def test_parse_summary_rootcauses_item_not_dict_raises():
    # rootCauses 항목이 dict 가 아니라 문자열이면 형식 위반으로 거른다.
    bad = {
        "situation": "상황",
        "rootCauses": ["원인 문자열"],
        "recommendations": [{"action": "조치", "rationale": "이유"}],
    }
    with pytest.raises(SummaryParseError):
        parse_summary(json.dumps(bad))


def test_parse_summary_rootcauses_item_missing_evidence_raises():
    # rootCauses 항목에 evidence 키가 빠지면 형식 위반으로 거른다.
    bad = {
        "situation": "상황",
        "rootCauses": [{"cause": "원인만 있음"}],
        "recommendations": [{"action": "조치", "rationale": "이유"}],
    }
    with pytest.raises(SummaryParseError):
        parse_summary(json.dumps(bad))


def test_parse_summary_recommendations_item_missing_rationale_raises():
    # recommendations 항목에 rationale 키가 빠지면 형식 위반으로 거른다.
    bad = {
        "situation": "상황",
        "rootCauses": [{"cause": "원인", "evidence": "근거"}],
        "recommendations": [{"action": "조치만 있음"}],
    }
    with pytest.raises(SummaryParseError):
        parse_summary(json.dumps(bad))
