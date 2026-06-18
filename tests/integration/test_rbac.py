"""역할 기반 접근 제어(RBAC) 통합 테스트(Postgres·Redis 컨테이너 필요).

require_role 게이트가 허용 역할만 통과시키는지 한곳에서 검증한다.
- 허용되지 않은 역할: 403
- 허용된 역할: 비-403(권한 통과 자체를 확인하는 것이 목적)

auth_headers 픽스처(conftest.py)로 역할별 토큰을 만든다.
"""

import pytest

pytestmark = pytest.mark.integration

# (이름, METHOD, 경로, 허용 역할 집합). 경로는 권한 게이트만 타도 충분하도록 고른다.
_CASES = [
    ("run_job_unknown", "POST", "/admin/run-job/anomaly_detection", {"ADM"}),
    ("reset_security", "POST", "/admin/reset/security", {"ADM"}),
    ("create_server", "POST", "/servers", {"ADM"}),
    ("delete_server", "DELETE", "/servers/999999", {"ADM"}),
]

_ALL_ROLES = ["STU", "MGR", "ADM"]


async def _call(client, method: str, path: str, headers: dict[str, str]):
    if method == "POST":
        # create_server 는 바디가 필요하므로 항상 유효한 페이로드를 함께 보낸다.
        # 권한 게이트가 막히면 바디는 평가되지 않고, 통과하면 정상 처리된다.
        return await client.post(path, headers=headers, json={
            "name": "rbac-srv", "ip": "10.9.9.9", "cpuCores": 4, "ramGb": 16,
        })
    return await client.delete(path, headers=headers)


@pytest.mark.parametrize("name,method,path,allowed", _CASES,
                         ids=[c[0] for c in _CASES])
async def test_rbac_forbids_disallowed_roles(client, auth_headers, name, method, path, allowed):
    for role in _ALL_ROLES:
        headers = await auth_headers(role)
        response = await _call(client, method, path, headers)
        if role in allowed:
            # 허용 역할: 권한 통과(403 아님). 404/200/201/409 등은 게이트 밖 처리 결과.
            assert response.status_code != 403, (
                f"{name}: {role} 는 허용돼야 하는데 403"
            )
        else:
            assert response.status_code == 403, (
                f"{name}: {role} 는 거부돼야 하는데 {response.status_code}"
            )
