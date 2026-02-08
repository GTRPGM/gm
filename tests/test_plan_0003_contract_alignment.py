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


@pytest.mark.asyncio
async def test_commit_state_defers_end_when_live_enemy_exists():
    state_client = MagicMock()
    state_client.commit = AsyncMock(return_value={"commit_id": "c1"})
    state_client.update_act = AsyncMock()
    state_client.update_sequence = AsyncMock()
    state_client.end_session = AsyncMock()
    state_client.get_state = AsyncMock(
        return_value={
            "current_sequence_id": "seq-3",
        }
    )
    state_client.get_sequence_details = AsyncMock(
        return_value={
            "sequence_id": "seq-3",
            "enemies": [
                {
                    "assigned_sequence_id": "seq-3",
                    "current_hp": 12,
                    "is_defeated": False,
                }
            ],
        }
    )

    engine = GameEngine(
        rule_client=MagicMock(),
        scenario_client=MagicMock(),
        state_client=state_client,
        llm=MagicMock(),
        db=MagicMock(),
    )

    scenario = ScenarioSuggestion(
        constraint_type=ScenarioConstraintType.MANDATORY,
        description="terminal",
        should_end=True,
    )
    state = {
        "session_id": "s1",
        "turn_id": "s1:1",
        "final_diffs": [],
        "scenario_suggestion": scenario,
    }

    await GameEngine.commit_state.__wrapped__(engine, state)

    state_client.end_session.assert_not_awaited()
    assert scenario.should_end is False


@pytest.mark.asyncio
async def test_commit_state_ends_when_no_live_enemy_exists():
    state_client = MagicMock()
    state_client.commit = AsyncMock(return_value={"commit_id": "c1"})
    state_client.update_act = AsyncMock()
    state_client.update_sequence = AsyncMock()
    state_client.end_session = AsyncMock()
    state_client.get_state = AsyncMock(
        return_value={
            "current_sequence_id": "seq-3",
        }
    )
    state_client.get_sequence_details = AsyncMock(
        return_value={
            "sequence_id": "seq-3",
            "enemies": [
                {
                    "assigned_sequence_id": "seq-3",
                    "current_hp": 0,
                    "is_defeated": True,
                }
            ],
        }
    )

    engine = GameEngine(
        rule_client=MagicMock(),
        scenario_client=MagicMock(),
        state_client=state_client,
        llm=MagicMock(),
        db=MagicMock(),
    )

    scenario = ScenarioSuggestion(
        constraint_type=ScenarioConstraintType.MANDATORY,
        description="terminal",
        should_end=True,
    )
    state = {
        "session_id": "s1",
        "turn_id": "s1:1",
        "final_diffs": [],
        "scenario_suggestion": scenario,
    }

    await GameEngine.commit_state.__wrapped__(engine, state)

    state_client.end_session.assert_awaited_once_with("s1")


@pytest.mark.asyncio
async def test_commit_state_still_defers_when_live_enemy_exists_even_if_input_is_terminal():
    state_client = MagicMock()
    state_client.commit = AsyncMock(return_value={"commit_id": "c1"})
    state_client.update_act = AsyncMock()
    state_client.update_sequence = AsyncMock()
    state_client.end_session = AsyncMock()
    state_client.get_state = AsyncMock(
        return_value={
            "current_sequence_id": "seq-6",
        }
    )
    state_client.get_sequence_details = AsyncMock(
        return_value={
            "sequence_id": "seq-6",
            "exit_triggers": ["핵심 적을 처치하고 봉인을 안정화한다."],
            "enemies": [
                {
                    "assigned_sequence_id": "seq-6",
                    "current_hp": 10,
                    "is_defeated": False,
                }
            ],
        }
    )

    engine = GameEngine(
        rule_client=MagicMock(),
        scenario_client=MagicMock(),
        state_client=state_client,
        llm=MagicMock(),
        db=MagicMock(),
    )

    scenario = ScenarioSuggestion(
        constraint_type=ScenarioConstraintType.MANDATORY,
        description="terminal",
        should_end=True,
    )
    state = {
        "session_id": "s1",
        "turn_id": "s1:1",
        "user_input": "핵심 적을 처치하고 봉인을 안정화한다.",
        "final_diffs": [],
        "scenario_suggestion": scenario,
    }

    await GameEngine.commit_state.__wrapped__(engine, state)

    state_client.end_session.assert_not_awaited()
    assert scenario.should_end is False


@pytest.mark.asyncio
async def test_commit_state_auto_ends_on_last_sequence_when_all_enemies_defeated():
    state_client = MagicMock()
    state_client.commit = AsyncMock(return_value={"commit_id": "c1"})
    state_client.update_act = AsyncMock()
    state_client.update_sequence = AsyncMock()
    state_client.end_session = AsyncMock()
    state_client.get_state = AsyncMock(
        return_value={
            "current_sequence_id": "seq-6",
        }
    )
    state_client.get_sequence_details = AsyncMock(
        return_value={
            "sequence_id": "seq-6",
            "enemies": [
                {
                    "assigned_sequence_id": "seq-6",
                    "current_hp": 0,
                    "is_defeated": True,
                },
                {
                    "assigned_sequence_id": "seq-6",
                    "current_hp": 0,
                    "is_defeated": True,
                },
            ],
        }
    )
    state_client.get_act_details = AsyncMock(
        return_value={
            "act_id": "act-3",
            "sequence_ids": ["seq-5", "seq-6"],
        }
    )

    engine = GameEngine(
        rule_client=MagicMock(),
        scenario_client=MagicMock(),
        state_client=state_client,
        llm=MagicMock(),
        db=MagicMock(),
    )

    scenario = ScenarioSuggestion(
        constraint_type=ScenarioConstraintType.ADVISORY,
        description="still active",
        should_end=False,
    )
    state = {
        "session_id": "s1",
        "turn_id": "s1:1",
        "final_diffs": [],
        "scenario_suggestion": scenario,
    }

    await GameEngine.commit_state.__wrapped__(engine, state)

    state_client.end_session.assert_awaited_once_with("s1")
    assert scenario.should_end is True
