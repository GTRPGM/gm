import httpx
import pytest

from gm.core.models.rule import RuleOutcome, RuleSuggestion
from gm.core.models.state import EntityDiff
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)


@pytest.mark.asyncio
async def test_rule_manager_complex_payload(respx_mock):
    client = RuleManagerHTTPClient()
    respx_mock.post("http://rule-engine:8050/play/scenario").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "123",
                    "scenario_id": "1",
                    "success": True,
                    "reason": "Action success",
                    "suggested": {"diffs": [], "relations": []},
                },
            },
        )
    )

    context = {
        "session_id": "123",
        "user_input": "Attack",
        "active_entity_id": "npc_456",
        "world_snapshot": {
            "player_id": "p1",
            "npcs": [
                {"id": "npc_456", "name": "Orc", "scenario_entity_id": "orc_master"}
            ],
            "enemies": [
                {
                    "id": "enemy_789",
                    "name": "Dragon",
                    "scenario_entity_id": "dragon_master",
                }
            ],
            "entity_relations": [
                {
                    "from_id": "orc_master",
                    "to_id": "dragon_master",
                    "relation_type": "HOSTILE",
                    "affinity": -50,
                }
            ],
            "player_npc_relations": [
                {"npc_id": "npc_456", "relation_type": "FRIENDLY", "affinity_score": 80}
            ],
        },
    }

    await client.get_proposal(context)

    request = respx_mock.calls.last.request
    import json

    payload = json.loads(request.content)

    assert len(payload["entities"]) == 3
    assert any(e["state_entity_id"] == "p1" for e in payload["entities"])
    assert any(e["state_entity_id"] == "npc_456" for e in payload["entities"])
    assert any(e["state_entity_id"] == "enemy_789" for e in payload["entities"])

    assert len(payload["relations"]) == 2
    assert any(
        r["cause_entity_id"] == "npc_456" and r["effect_entity_id"] == "enemy_789"
        for r in payload["relations"]
    )
    assert any(
        r["cause_entity_id"] == "p1" and r["effect_entity_id"] == "npc_456"
        for r in payload["relations"]
    )


@pytest.mark.asyncio
async def test_scenario_manager_error_handling(respx_mock):
    client = ScenarioManagerHTTPClient()

    # 404 Case
    respx_mock.post("http://scenario-service:8040/api/v1/check/validate").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    outcome = RuleOutcome(
        session_id="1",
        scenario_id="1",
        success=True,
        reason="ok",
        suggested=RuleSuggestion(),
    )

    context = {"rule_outcome": outcome, "world_snapshot": {"scenario_id": "1"}}

    with pytest.raises(ValueError, match="Scenario Context Missing"):
        await client.get_proposal(context)


@pytest.mark.asyncio
async def test_state_manager_methods(respx_mock):
    client = StateManagerHTTPClient()

    # commit
    respx_mock.post("http://state-manager:8030/state/commit").mock(
        return_value=httpx.Response(
            200, json={"status": "success", "data": {"commit_id": "c1"}}
        )
    )
    res = await client.commit("t1", [EntityDiff(entity_id="e1", diff={})])
    assert res["commit_id"] == "c1"

    # get_state
    respx_mock.get("http://state-manager:8030/state/session/s1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "s1",
                    "world_snapshot": {"player_id": "p1", "npcs": [], "enemies": []},
                },
            },
        )
    )
    res = await client.get_state("s1")
    assert "world_snapshot" in res

    # get_sequence_details
    res = await client.get_sequence_details("s1")
    assert "npcs" in res
    assert "enemies" in res


@pytest.mark.asyncio
async def test_health_checks(respx_mock):
    respx_mock.get("http://rule-engine:8050/health").mock(
        return_value=httpx.Response(200)
    )
    assert await RuleManagerHTTPClient().check_health() is True

    respx_mock.get("http://scenario-service:8040/health").mock(
        return_value=httpx.Response(200)
    )
    assert await ScenarioManagerHTTPClient().check_health() is True

    respx_mock.get("http://state-manager:8030/health").mock(
        return_value=httpx.Response(200)
    )
    assert await StateManagerHTTPClient().check_health() is True
