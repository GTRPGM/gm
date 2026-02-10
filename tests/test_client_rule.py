import httpx
import pytest
import json
from gm.core.config import settings
from gm.plugins.external.http_client import RuleManagerHTTPClient

@pytest.mark.asyncio
async def test_rule_manager_client_payload(respx_mock):
    client = RuleManagerHTTPClient()
    mock_data = {
        "session_id": "123",
        "scenario_id": "1",
        "success": True,
        "reason": "OK",
        "suggested": {"diffs": [], "relations": []}
    }
    # conftest의 mock을 덮어쓰기 위해 더 구체적인 설정 또는 명시적 호출 확인
    respx_mock.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": mock_data})
    )

    context = {
        "session_id": "123",
        "user_input": "attack",
        "world_snapshot": {"player_id": "p1", "npcs": [], "enemies": []}
    }
    await client.get_proposal(context)
    assert respx_mock.calls.last.request.method == "POST"


@pytest.mark.asyncio
async def test_gm_passes_relations_to_rule_engine(respx_mock):
    client = RuleManagerHTTPClient()
    mock_data = {
        "session_id": "test_session",
        "scenario_id": "1",
        "success": True,
        "reason": "OK",
        "suggested": {"diffs": [], "relations": []}
    }
    respx_mock.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": mock_data})
    )

    context = {
        "session_id": "test_session",
        "user_input": "attack",
        "world_snapshot": {
            "player_id": "p1",
            "npcs": [{"id": "npc_A", "name": "NPC A", "scenario_entity_id": "A"}],
            "enemies": [{"id": "enemy_B", "name": "Enemy B", "scenario_entity_id": "B"}],
            "entity_relations": [
                {"from_id": "A", "to_id": "B", "relation_type": "HOSTILE", "affinity": -10}
            ]
        }
    }

    await client.get_proposal(context)
    payload = json.loads(respx_mock.calls.last.request.content)
    # npc_A, enemy_B가 entities에 포함되어야 관계가 필터링되지 않음
    assert len(payload["relations"]) == 1
    assert payload["relations"][0]["cause_entity_id"] == "npc_A"
    assert payload["relations"][0]["effect_entity_id"] == "enemy_B"