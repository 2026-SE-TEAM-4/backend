"""팀 목록 API 통합 테스트(Postgres·Redis 컨테이너 필요)."""

import pytest

pytestmark = pytest.mark.integration


async def test_list_teams_is_public(client):
    """회원가입 전 단계라 인증 없이 팀 목록을 받는다. 시드 팀 LAB-A 포함."""
    res = await client.get("/teams")
    assert res.status_code == 200
    teams = res.json()["teams"]
    assert any(t["code"] == "LAB-A" for t in teams)
    assert all({"id", "name", "code"} <= set(t) for t in teams)
