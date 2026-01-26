import pytest
from httpx import Response

from gm.core.config import settings
from gm.core.engine.game_engine import GameEngine
from gm.infra.db.database import db
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel


def get_test_engine():
    return GameEngine(
        rule_client=RuleManagerHTTPClient(),
        scenario_client=ScenarioManagerHTTPClient(),
        state_client=StateManagerHTTPClient(),
        llm=NarrativeChatModel(),
        db=db,
    )


def create_chat_completion_response(content: str) -> dict:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
    }


@pytest.mark.asyncio
async def test_conflict_resolution_scenario_wins(mock_external_services):
    """
    Precision Test 1: Conflict Resolution
    Rule validates an action but Scenario corrects the value.
    Expectation: The final state reflects the Scenario's correction.
    """
    # 1. Clear default mocks from fixture
    mock_external_services.routes.clear()

    # 2. Setup Specific Mocks

    # Rule: Suggests damage 10
    mock_external_services.post(f"{settings.RULE_SERVICE_URL}/api/v1/rule/check").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "sess_conflict",
                    "scenario_id": 1,
                    "phase_type": "COMBAT",
                    "reason": "Rule Check",
                    "success": True,
                    "suggested": {
                        "diffs": [{"entity_id": "player", "diff": {"hp": -10}}],
                        "relations": [],
                    },
                    "value_range": None,
                },
                "message": "OK",
            },
        )
    )

    # Scenario: Corrects damage to 5 (e.g., defensive buff)
    mock_external_services.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/scenario/check"
    ).mock(
        return_value=Response(
            200,
            json={
                "constraint_type": "advisory",
                "description": "Scenario Check",
                "correction_diffs": [{"entity_id": "player", "diff": {"hp": -5}}],
                "narrative_slot": None,
            },
        )
    )

    # State: Success
    mock_external_services.post(
        f"{settings.STATE_SERVICE_URL}/api/v1/state/commit"
    ).mock(
        return_value=Response(
            200, json={"commit_id": "commit_conflict_test", "status": "success"}
        )
    )

    # LLM: Standard
    mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    ).mock(
        return_value=Response(
            200, json=create_chat_completion_response("Conflict resolved.")
        )
    )

    # 3. Execute Pipeline
    initial_state = {
        "session_id": "sess_conflict",
        "user_input": "Attack",
        "is_npc_turn": False,
        "active_entity_id": "player",
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "COMBAT",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player", "goblin"]},
    }

    engine = get_test_engine()
    final_state = await engine.graph.ainvoke(initial_state)

    # 4. Verify
    # Extract final diffs
    final_diffs = final_state["final_diffs"]
    assert len(final_diffs) == 1

    player_diff = next((d for d in final_diffs if d.entity_id == "player"), None)
    assert player_diff is not None

    # Should be -5 (Scenario), not -10 (Rule)
    assert player_diff.diff["hp"] == -5


@pytest.mark.asyncio
async def test_narrative_retry_logic(mock_external_services):
    """
    Precision Test 2: Narrative Retry
    Scenario requires a specific slot word. LLM fails first, succeeds second.
    Expectation: Pipeline retries and returns the valid narrative.
    """
    mock_external_services.routes.clear()

    # Rule & Scenario Setup
    mock_external_services.post(f"{settings.RULE_SERVICE_URL}/api/v1/rule/check").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "sess_retry",
                    "scenario_id": 1,
                    "phase_type": "EXPLORATION",
                    "reason": "Rule Check",
                    "success": True,
                    "suggested": {"diffs": [], "relations": []},
                    "value_range": None,
                },
                "message": "OK",
            },
        )
    )

    # Scenario demands "SECRET_KEY" in narrative
    mock_external_services.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/scenario/check"
    ).mock(
        return_value=Response(
            200,
            json={
                "constraint_type": "advisory",
                "description": "Scenario Check",
                "correction_diffs": [],
                "narrative_slot": "SECRET_KEY",
            },
        )
    )

    mock_external_services.post(
        f"{settings.STATE_SERVICE_URL}/api/v1/state/commit"
    ).mock(return_value=Response(200, json={"commit_id": "commit_retry_test"}))

    # LLM: First attempt fail, Second attempt success
    llm_route = mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    )
    llm_route.side_effect = [
        Response(
            200, json=create_chat_completion_response("Just a normal story.")
        ),  # Missing slot
        Response(
            200, json=create_chat_completion_response("You found the SECRET_KEY!")
        ),  # Has slot
    ]

    # Execute
    initial_state = {
        "session_id": "sess_retry",
        "user_input": "Look around",
        "is_npc_turn": False,
        "active_entity_id": "player",
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "EXPLORATION",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player", "chest"]},
    }

    engine = get_test_engine()
    final_state = await engine.graph.ainvoke(initial_state)

    # Verify
    assert "SECRET_KEY" in final_state["narrative"]
    assert llm_route.call_count == 2


@pytest.mark.asyncio
async def test_pipeline_halts_on_state_error(mock_external_services):
    """
    Precision Test 3: Error Handling
    State Manager returns 500 Error.
    Expectation: Pipeline raises exception and stops (does not generate narrative).
    """
    mock_external_services.routes.clear()

    mock_external_services.post(f"{settings.RULE_SERVICE_URL}/api/v1/rule/check").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "sess_error",
                    "scenario_id": 1,
                    "phase_type": "MENU",
                    "reason": "Rule Check",
                    "success": True,
                    "suggested": {"diffs": [], "relations": []},
                    "value_range": None,
                },
                "message": "OK",
            },
        )
    )
    mock_external_services.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/scenario/check"
    ).mock(
        return_value=Response(
            200,
            json={
                "constraint_type": "advisory",
                "description": "Scenario Check",
                "correction_diffs": [],
                "narrative_slot": None,
            },
        )
    )

    # State Manager Fails
    mock_external_services.post(
        f"{settings.STATE_SERVICE_URL}/api/v1/state/commit"
    ).mock(return_value=Response(500, json={"error": "Database unavailable"}))

    # LLM should NOT be called
    llm_route = mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    ).mock(
        return_value=Response(
            200, json=create_chat_completion_response("Should not see this")
        )
    )

    # Execute
    initial_state = {
        "session_id": "sess_error",
        "user_input": "Save game",
        "is_npc_turn": False,
        "active_entity_id": "player",
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "MENU",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player"]},
    }

    # Expect exception
    engine = get_test_engine()

    # Patch the state client to raise an error, overriding the hardcoded mock
    import httpx

    # Create a dummy request/response for the error
    request = httpx.Request("POST", "http://mock/commit")
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError(
        "500 Internal Server Error", request=request, response=response
    )

    # We need to patch the commit method to raise this error
    # Since commit is async, we need a side_effect that raises
    from unittest.mock import MagicMock

    engine.state_client.commit = MagicMock(side_effect=error)

    with pytest.raises(httpx.HTTPStatusError):
        await engine.graph.ainvoke(initial_state)

    # Verify LLM was not called
    assert llm_route.call_count == 0


@pytest.mark.asyncio
async def test_npc_turn_workflow(mock_external_services):
    """
    Precision Test 4: NPC Turn Workflow
    Verifies that the NPC turn logic generates input and proceeds through the pipeline.
    """
    mock_external_services.routes.clear()

    # Rule Check
    mock_external_services.post(f"{settings.RULE_SERVICE_URL}/api/v1/rule/check").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "sess_npc",
                    "scenario_id": 1,
                    "phase_type": "COMBAT",
                    "reason": "NPC Rule Check",
                    "success": True,
                    "suggested": {"diffs": [], "relations": []},
                    "value_range": None,
                },
                "message": "OK",
            },
        )
    )

    # Scenario Check
    mock_external_services.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/scenario/check"
    ).mock(
        return_value=Response(
            200,
            json={
                "constraint_type": "advisory",
                "description": "NPC Scenario Check",
                "correction_diffs": [],
                "narrative_slot": None,
            },
        )
    )

    # State Commit
    mock_external_services.post(
        f"{settings.STATE_SERVICE_URL}/api/v1/state/commit"
    ).mock(return_value=Response(200, json={"commit_id": "commit_npc_test"}))

    llm_chat_route = mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    )
    llm_chat_route.side_effect = [
        Response(200, json=create_chat_completion_response("npc_1")),  # Select Actor
        Response(
            200, json=create_chat_completion_response("The NPC attacks!")
        ),  # Generate NPC Action (via chat completion now)
        Response(
            200,
            json=create_chat_completion_response(
                "Narrative: The NPC attacks aggressively!"
            ),
        ),  # Generate Narrative
    ]

    # Execute
    initial_state = {
        "session_id": "sess_npc",
        "user_input": "",  # Empty initially
        "is_npc_turn": True,
        "active_entity_id": "",  # Pending selection
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "COMBAT",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player", "npc_1"]},
    }

    engine = get_test_engine()
    final_state = await engine.graph.ainvoke(initial_state)

    # Verify
    assert final_state["active_entity_id"] == "npc_1"
    assert final_state["user_input"] == "The NPC attacks!"
    assert final_state["narrative"] == "Narrative: The NPC attacks aggressively!"
    assert llm_chat_route.call_count == 3
