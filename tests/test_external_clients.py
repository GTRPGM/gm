import httpx
import pytest

from gm.core.config import settings
from gm.schemas.rule_engine import RuleOutcome
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
)


@pytest.mark.asyncio
async def test_rule_manager_client_payload(respx_mock):
    client = RuleManagerHTTPClient()

    # Mock the rule engine response
    route = respx_mock.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "123",
                    "scenario_id": "1",
                    "phase_type": "탐험",
                    "reason": "OK",
                    "success": True,
                    "suggested": {"diffs": [], "relations": []},
                },
                "message": "OK",
            },
        )
    )

    context = {
        "session_id": "123",
        "user_input": "Test action",
        "scenario_id": "1",
        "world_snapshot": {
            "player_id": "player_1",
            "player_name": "Hero",
            "npcs": [],
            "enemies": [],
        },
    }

    result = await client.get_proposal(context)

    assert isinstance(result, RuleOutcome)
    assert result.session_id == "123"

    # Check if payload was correctly formatted
    request_data = route.calls.last.request.content.decode()
    import json

    payload = json.loads(request_data)

    assert payload["session_id"] == "123"
    # RuleRequestEntity uses state_entity_id
    assert payload["entities"][0]["state_entity_id"] == "player_1"
    assert "locale_id" in payload


@pytest.mark.asyncio
async def test_scenario_manager_client_payload(respx_mock):
    client = ScenarioManagerHTTPClient()

    # Mock Scenario Service /api/v1/check/validate
    route = respx_mock.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "is_triggered": True,
                "reason": "Triggered by scenario",
                "suggested_narration": "The prophecy unfolds...",
            },
        )
    )

    rule_outcome = RuleOutcome(
        session_id="123",
        scenario_id="1",
        reason="Action result",
        success=True,
        suggested={"diffs": [], "relations": []},
    )

    context = {
        "user_input": "User input",
        "rule_outcome": rule_outcome,
        "world_snapshot": {"scenario_id": "1"},
    }

    result = await client.get_proposal(context)

    assert result.constraint_type.value == "mandatory"
    assert result.narrative_slot == "The prophecy unfolds..."

    # Check payload
    request_data = route.calls.last.request.content.decode()
    import json

    payload = json.loads(request_data)

    assert payload["scenario_id"] == "1"
    assert payload["user_input"] == "User input"
