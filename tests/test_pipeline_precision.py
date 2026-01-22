import pytest
from httpx import HTTPStatusError, Response

from gm.core.config import settings
from gm.services.graph import turn_pipeline


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
                "description": "Rule Check",
                "success": True,
                "suggested_diffs": [{"entity_id": "player", "diff": {"hp": -10}}],
                "required_entities": [],
                "value_range": None,
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
    }
    final_state = await turn_pipeline.ainvoke(initial_state)

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
                "description": "Rule Check",
                "success": True,
                "suggested_diffs": [],
                "required_entities": [],
                "value_range": None,
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
    }
    final_state = await turn_pipeline.ainvoke(initial_state)

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
                "description": "Rule Check",
                "success": True,
                "suggested_diffs": [],
                "required_entities": [],
                "value_range": None,
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
    }

    # Expect exception
    with pytest.raises(HTTPStatusError):
        await turn_pipeline.ainvoke(initial_state)

    # Verify LLM was not called
    assert llm_route.call_count == 0


@pytest.mark.asyncio
async def test_npc_turn_workflow(mock_external_services):
    """
    Precision Test 4: NPC Turn Workflow
    Verifies that the NPC turn logic generates input and proceeds through the pipeline.
    """
    mock_external_services.routes.clear()

    # NPC Action Generation
    mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/llm/npc-action"
    ).mock(
        return_value=Response(200, json={"action_text": "NPC attacks aggressively!"})
    )

    # Rule Check
    mock_external_services.post(f"{settings.RULE_SERVICE_URL}/api/v1/rule/check").mock(
        return_value=Response(
            200,
            json={
                "description": "NPC Rule Check",
                "success": True,
                "suggested_diffs": [],
                "required_entities": [],
                "value_range": None,
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

    # Narrative Generation
    mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    ).mock(
        return_value=Response(
            200, json=create_chat_completion_response("The NPC attacks!")
        )
    )

    # Execute
    initial_state = {
        "session_id": "sess_npc",
        "user_input": "",  # Empty initially
        "is_npc_turn": True,
    }
    final_state = await turn_pipeline.ainvoke(initial_state)

    # Verify
    assert final_state["user_input"] == "NPC attacks aggressively!"
    assert final_state["narrative"] == "The NPC attacks!"
