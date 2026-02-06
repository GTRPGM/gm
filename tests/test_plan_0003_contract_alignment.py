from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from gm.core.config import settings
from gm.core.engine.game_engine import GameEngine
from gm.plugins.external.http_client import (
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion


@pytest.mark.asyncio
async def test_state_update_act_payload_matches_state_contract(respx_mock):
    client = StateManagerHTTPClient()
    route = respx_mock.put(f"{settings.STATE_MANAGER_URL}/state/session/s1/act").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {}})
    )

    await client.update_act("s1", "act-2", "seq-2-1")

    import json

    payload = json.loads(route.calls.last.request.content.decode())
    assert payload["new_act"] == 2
    assert payload["new_act_id"] == "act-2"
    assert payload["new_sequence_id"] == "seq-2-1"


@pytest.mark.asyncio
async def test_state_update_sequence_payload_matches_state_contract(respx_mock):
    client = StateManagerHTTPClient()
    route = respx_mock.put(
        f"{settings.STATE_MANAGER_URL}/state/session/s1/sequence"
    ).mock(return_value=httpx.Response(200, json={"status": "success", "data": {}}))

    await client.update_sequence("s1", "seq-3")

    import json

    payload = json.loads(route.calls.last.request.content.decode())
    assert payload["new_sequence"] == 3
    assert payload["new_sequence_id"] == "seq-3"


@pytest.mark.asyncio
async def test_scenario_manager_accepts_wrapped_response(respx_mock):
    client = ScenarioManagerHTTPClient()
    respx_mock.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "is_triggered": True,
                    "reason": "wrapped",
                    "next_act_id": "act-2",
                    "next_seq_id": "seq-2-1",
                    "suggested_narration": "narr",
                },
            },
        )
    )

    context = {
        "rule_outcome": MagicMock(scenario_id="scn-1"),
        "world_snapshot": {"scenario_id": "scn-1"},
        "user_input": "go",
    }
    result = await client.get_proposal(context)
    assert result.constraint_type == ScenarioConstraintType.MANDATORY
    assert result.next_act_id == "act-2"
    assert result.next_seq_id == "seq-2-1"


@pytest.mark.asyncio
async def test_commit_state_requires_next_seq_when_next_act_is_set():
    state_client = MagicMock()
    state_client.commit = AsyncMock(return_value={"commit_id": "c1"})
    state_client.update_act = AsyncMock()
    state_client.update_sequence = AsyncMock()

    engine = GameEngine(
        rule_client=MagicMock(),
        scenario_client=MagicMock(),
        state_client=state_client,
        llm=MagicMock(),
        db=MagicMock(),
    )

    state = {
        "session_id": "s1",
        "turn_id": "s1:1",
        "final_diffs": [],
        "scenario_suggestion": ScenarioSuggestion(
            constraint_type=ScenarioConstraintType.MANDATORY,
            description="transition",
            next_act_id="act-2",
            next_seq_id=None,
        ),
    }

    with pytest.raises(ValueError, match="next_seq_id is required"):
        await GameEngine.commit_state.__wrapped__(engine, state)
