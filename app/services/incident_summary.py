"""LLM 원인 요약 순수 로직(UC25). DB·네트워크 비의존.

요약 잡(incident_summary_job)이 이미 조회한 평문 데이터를 넘겨 호출한다. 이 모듈은
프롬프트 조립(build_context·build_prompt)과 응답 파싱(parse_summary)만 담당하며,
Gemini 호출 자체는 잡이 주입한 클라이언트로 수행한다.

순수 함수로 두는 이유: 네트워크(Gemini)를 잡에서 떼어내 결정적으로 단위 테스트하기
위함이다. 입력은 "준비된 평문 데이터", 출력은 프롬프트 문자열과 파싱된 요약이다.

안전장치(설계 D-4): LLM 은 읽기 전용 분석만 한다. 여기서 만든 요약은 자문용으로
저장·표시만 하며, 어떤 자동 조치도 트리거하지 않는다.
"""

import json
from dataclasses import dataclass


class SummaryParseError(ValueError):
    """모델 응답이 기대한 JSON 형식이 아닐 때 던진다(잡이 건너뛸 신호)."""


@dataclass(frozen=True)
class ParsedSummary:
    """파싱된 요약 한 건. IncidentSummary 모델에 그대로 저장할 수 있는 형태."""

    situation: str
    root_causes: list[dict[str, str]]  # [{cause, evidence}]
    recommendations: list[dict[str, str]]  # [{action, rationale}]


def build_context(
    incident: dict,
    anomalies: list[dict],
    server_metrics: list[dict],
    servers: list[dict],
) -> dict:
    """인시던트·이상·관련 메트릭·서버 메타를 JSON 직렬화 가능한 컨텍스트로 묶는다.

    DB 세션이 아니라 이미 조회한 평문 dict 를 받는다(잡이 조회 책임을 진다).
    응답 계약과 일관되게 camelCase 키로 정규화해 프롬프트에 싣는다.
    """
    return {
        "incident": {
            "id": incident["id"],
            "severity": incident["severity"],
            "status": incident["status"],
            "serverIds": incident["server_ids"],
        },
        "anomalies": [
            {
                "serverId": anomaly["server_id"],
                "metric": anomaly["metric"],
                "currentValue": anomaly["current_value"],
                "mean": anomaly["mean"],
                "stddev": anomaly["stddev"],
                "detectedAt": anomaly["detected_at"],
            }
            for anomaly in anomalies
        ],
        "servers": [
            {
                "id": server["id"],
                "name": server["name"],
                "groupName": server["group_name"],
            }
            for server in servers
        ],
        "serverMetrics": [
            {
                "serverId": metric["server_id"],
                "cpuUsage": metric["cpu_usage"],
                "memUsage": metric["mem_usage"],
                "collectedAt": metric["collected_at"],
            }
            for metric in server_metrics
        ],
    }


def build_prompt(context: dict) -> str:
    """컨텍스트를 근거로 한국어 요약을 요청하는 프롬프트를 만든다.

    환각 억제(설계 D-4): "주어진 데이터에 없으면 추측 금지"를 명시하고, 각 주장 뒤에
    근거 데이터(서버/시각/값)를 괄호로 인용하도록 요구한다. 응답은 STRICT JSON 으로
    받아 파싱을 결정적으로 만든다.
    """
    data_json = json.dumps(context, ensure_ascii=False, indent=2)
    return (
        "다음 운영 데이터만 근거로 인시던트를 한국어로 요약하라.\n"
        "①상황 ②원인 후보 ③권장 조치 순으로 정리한다.\n"
        "각 주장 뒤에는 근거 데이터(서버/시각/값)를 괄호로 인용한다.\n"
        "주어진 데이터에 없는 내용은 추측하지 말고, 데이터로 뒷받침되는 것만 적는다.\n\n"
        "반드시 아래 키를 가진 STRICT JSON 한 개만 출력한다(설명·코드펜스 없이):\n"
        '{\n'
        '  "situation": "상황 요약 문자열",\n'
        '  "rootCauses": [{"cause": "원인", "evidence": "근거 데이터"}],\n'
        '  "recommendations": [{"action": "권장 조치", "rationale": "근거"}]\n'
        '}\n\n'
        "운영 데이터:\n"
        f"{data_json}\n"
    )


def parse_summary(response_text: str) -> ParsedSummary:
    """모델의 JSON 텍스트를 ParsedSummary 로 파싱한다. 형식이 깨지면 SummaryParseError.

    모델이 ```json ... ``` 코드펜스로 감싸 보내는 경우가 흔하므로 펜스를 벗겨 파싱한다.
    필수 키(situation/rootCauses/recommendations)가 빠지면 형식 위반으로 거른다.
    """
    cleaned = _strip_code_fence(response_text)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as error:
        raise SummaryParseError(f"요약 응답이 JSON 이 아닙니다: {error}") from error

    if not isinstance(data, dict):
        raise SummaryParseError("요약 응답 최상위가 JSON 객체가 아닙니다.")

    missing = {"situation", "rootCauses", "recommendations"} - data.keys()
    if missing:
        raise SummaryParseError(f"요약 응답에 필수 키가 없습니다: {sorted(missing)}")

    # 프롬프트가 항목별 STRICT 키까지 요구하므로 최상위뿐 아니라 항목 모양도 검증한다.
    # 깨진 항목을 그대로 저장하면 API·프런트가 cause/evidence 를 꺼낼 때 KeyError 가 난다.
    root_causes = _require_items(data["rootCauses"], "rootCauses", ("cause", "evidence"))
    recommendations = _require_items(
        data["recommendations"], "recommendations", ("action", "rationale")
    )

    return ParsedSummary(
        situation=str(data["situation"]),
        root_causes=root_causes,
        recommendations=recommendations,
    )


def _require_items(
    value: object, field: str, required_keys: tuple[str, ...]
) -> list[dict[str, str]]:
    """리스트의 각 항목이 required_keys 를 가진 dict 인지 확인하고 아니면 거른다.

    모델이 키 이름을 어기거나 항목을 문자열로 보내는 경우를 잡아 SummaryParseError 로
    바꾼다. 잡은 이 신호를 받아 해당 인시던트만 건너뛴다(저장하지 않는다).
    """
    if not isinstance(value, list):
        raise SummaryParseError(f"요약 응답의 {field} 가 리스트가 아닙니다.")
    items: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise SummaryParseError(f"요약 응답의 {field} 항목이 객체가 아닙니다.")
        missing = set(required_keys) - item.keys()
        if missing:
            raise SummaryParseError(
                f"요약 응답의 {field} 항목에 필수 키가 없습니다: {sorted(missing)}"
            )
        items.append({key: str(item[key]) for key in required_keys})
    return items


def _strip_code_fence(text: str) -> str:
    """```json ... ``` 또는 ``` ... ``` 코드펜스를 벗겨 안쪽 JSON 만 남긴다.

    펜스가 없으면 원문을 그대로 돌려준다. 모델이 펜스로 감싸 보내도 파싱이 깨지지
    않게 하기 위함이다.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # 첫 줄의 ``` 또는 ```json 과 마지막 줄의 ``` 를 제거한다.
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
