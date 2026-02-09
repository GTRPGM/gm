from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import Response

from gm.core.config import settings
from gm.core.engine.game_engine import GameEngine
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel
from gm.schemas.rule_engine import RuleOutcome, RuleSuggestion
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion


def get_test_engine(db_handler):
    return GameEngine(
        rule_client=RuleManagerHTTPClient(),
        scenario_client=ScenarioManagerHTTPClient(),
        state_client=StateManagerHTTPClient(),
        llm=NarrativeChatModel(),
        db=db_handler,
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
async def test_process_player_turn_skips_npc_when_should_end(mock_db_handler):
    engine = get_test_engine(mock_db_handler)

    engine.graph = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value={
                "turn_id": "s1:3",
                "narrative": "종료",
                "commit_id": "c1",
                "active_entity_id": "player",
                "world_snapshot": {"entities": ["enemy-1"]},
                "scenario_suggestion": ScenarioSuggestion(
                    constraint_type=ScenarioConstraintType.MANDATORY,
                    description="terminal",
                    should_end=True,
                ),
            }
        )
    )
    engine.process_npc_turn = AsyncMock()

    result = await engine.process_player_turn(
        SimpleNamespace(session_id="s1", content="마무리한다")
    )

    engine.process_npc_turn.assert_not_awaited()
    assert result["npc_turn"] is None


@pytest.mark.asyncio
async def test_process_player_turn_skips_npc_on_sequence_transition(mock_db_handler):
    engine = get_test_engine(mock_db_handler)

    engine.state_client.get_state = AsyncMock(
        side_effect=[
            {"current_sequence_id": "seq-1", "status": "active"},
            {"current_sequence_id": "seq-2", "status": "active"},
        ]
    )
    engine.graph = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value={
                "turn_id": "s1:1",
                "narrative": "전환",
                "commit_id": "c2",
                "active_entity_id": "player",
                "world_snapshot": {"entities": ["npc-1"]},
                "scenario_suggestion": ScenarioSuggestion(
                    constraint_type=ScenarioConstraintType.MANDATORY,
                    description="transition",
                    should_end=False,
                ),
            }
        )
    )
    engine.process_npc_turn = AsyncMock()

    result = await engine.process_player_turn(
        SimpleNamespace(session_id="s1", content="다음 시퀀스로 이동")
    )

    engine.process_npc_turn.assert_not_awaited()
    assert result["npc_turn"] is None


@pytest.mark.asyncio
async def test_check_rule_fallback_on_rule_engine_error(mock_db_handler):
    engine = get_test_engine(mock_db_handler)
    engine.rule_client.get_proposal = AsyncMock(side_effect=RuntimeError("boom"))

    result = await engine.check_rule(
        {"session_id": "s1", "scenario_id": "scn-1", "active_entity_id": "player"}
    )

    assert result["rule_outcome"].success is True
    assert result["rule_outcome"].scenario_id == "scn-1"


@pytest.mark.asyncio
async def test_check_rule_selects_random_target_when_not_specified(mock_db_handler):
    engine = get_test_engine(mock_db_handler)
    engine.rule_client.get_proposal = AsyncMock(
        return_value=RuleOutcome(
            session_id="s1",
            scenario_id="scn-1",
            success=True,
            reason="ok",
            suggested=RuleSuggestion(),
        )
    )

    state = {
        "session_id": "s1",
        "scenario_id": "scn-1",
        "active_entity_id": "player",
        "sequence_type": "COMBAT",
        "turn_id": "s1:1",
        "user_input": "공격한다.",
        "world_snapshot": {
            "enemies": [
                {
                    "id": "enemy-state-1",
                    "scenario_enemy_id": "enemy-wolf-1",
                    "name": "폐허 늑대",
                    "current_hp": 30,
                },
                {
                    "id": "enemy-state-2",
                    "scenario_enemy_id": "enemy-slime-1",
                    "name": "산성 슬라임",
                    "current_hp": 30,
                },
            ]
        },
    }

    result = await engine.check_rule(state)

    assert result["target_selection_mode"] == "random"
    assert result["selected_target_entity_id"] in {"enemy-state-1", "enemy-state-2"}
    called_context = engine.rule_client.get_proposal.await_args.args[0]
    assert (
        called_context["selected_target_entity_id"]
        == result["selected_target_entity_id"]
    )


@pytest.mark.asyncio
async def test_check_rule_uses_explicit_target_when_mentioned(mock_db_handler):
    engine = get_test_engine(mock_db_handler)
    engine.rule_client.get_proposal = AsyncMock(
        return_value=RuleOutcome(
            session_id="s1",
            scenario_id="scn-1",
            success=True,
            reason="ok",
            suggested=RuleSuggestion(),
        )
    )

    state = {
        "session_id": "s1",
        "scenario_id": "scn-1",
        "active_entity_id": "player",
        "sequence_type": "COMBAT",
        "turn_id": "s1:2",
        "user_input": "산성 슬라임을 벤다.",
        "world_snapshot": {
            "enemies": [
                {
                    "id": "enemy-state-1",
                    "scenario_enemy_id": "enemy-wolf-1",
                    "name": "폐허 늑대",
                    "current_hp": 30,
                },
                {
                    "id": "enemy-state-2",
                    "scenario_enemy_id": "enemy-slime-1",
                    "name": "산성 슬라임",
                    "current_hp": 30,
                },
            ]
        },
    }

    result = await engine.check_rule(state)

    assert result["target_selection_mode"] == "explicit"
    assert result["selected_target_entity_id"] == "enemy-state-2"
    assert result["selected_target_name"] == "산성 슬라임"


@pytest.mark.asyncio
async def test_conflict_resolution_scenario_wins(
    mock_external_services, mock_db_handler
):
    """
    Precision Test 1: Conflict Resolution
    Rule validates an action but Scenario corrects the value.
    Expectation: The final state reflects the Scenario's correction.
    """
    # 1. Clear default mocks from fixture
    mock_external_services.routes.clear()

    # 2. Setup Specific Mocks

    # Rule: Suggests damage 10
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "12345",
                    "scenario_id": "1",
                    "phase_type": "COMBAT",
                    "reason": "Rule Check",
                    "success": True,
                    "suggested": {
                        "diffs": [{"state_entity_id": "player", "diff": {"hp": -10}}],
                        "relations": [],
                    },
                    "value_range": None,
                },
                "message": "OK",
            },
        )
    )

    # Scenario: Corrects damage to 5 (Aligned with /api/v1/check/validate)
    mock_external_services.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"
    ).mock(
        return_value=Response(
            200,
            json={
                "is_triggered": True,
                "reason": "Scenario Check",
                "next_act_id": None,
                "next_seq_id": None,
                "suggested_narration": "Corrected by scenario",
            },
        )
    )

    # State: Success
    mock_external_services.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(
            200, json={"commit_id": "commit_conflict_test", "status": "success"}
        )
    )

    # Mock get_state as well since routes were cleared
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/[^/]+$"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "12345",
                    "world_snapshot": {"player_id": "player"},
                },
            },
        )
    )
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*/sequence/details"
    ).mock(
        return_value=Response(
            200, json={"status": "success", "data": {"npcs": [], "enemies": []}}
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
        "session_id": "12345",
        "user_input": "Attack",
        "is_npc_turn": False,
        "active_entity_id": "player",
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "COMBAT",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player", "goblin"]},
    }

    engine = get_test_engine(mock_db_handler)
    final_state = await engine.graph.ainvoke(initial_state)

    # 4. Verify
    # Extract final diffs
    final_diffs = final_state["final_diffs"]
    assert len(final_diffs) == 1

    player_diff = next((d for d in final_diffs if d.entity_id == "player"), None)
    assert player_diff is not None

    # Should be -10 (Rule), as Scenario API currently doesn't return correction_diffs
    assert player_diff.diff["hp"] == -10


@pytest.mark.asyncio
async def test_narrative_retry_logic(mock_external_services, mock_db_handler):
    """
    Precision Test 2: Narrative Slot Is Not Enforced
    Scenario may provide suggested_narration, but GM should not force it.
    Expectation: Pipeline accepts first valid generation without slot retry.
    """
    mock_external_services.routes.clear()

    # Rule & Scenario Setup
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "999",
                    "scenario_id": "1",
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

    # Scenario may suggest "SECRET_KEY" but should not force it.
    mock_external_services.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"
    ).mock(
        return_value=Response(
            200,
            json={
                "is_triggered": True,
                "reason": "Scenario Check",
                "next_act_id": None,
                "next_seq_id": None,
                "suggested_narration": "SECRET_KEY",
            },
        )
    )

    mock_external_services.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(200, json={"commit_id": "commit_retry_test"})
    )

    # Mock get_state as well
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/[^/]+$"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "999",
                    "world_snapshot": {"player_id": "player"},
                },
            },
        )
    )
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*/sequence/details"
    ).mock(
        return_value=Response(
            200, json={"status": "success", "data": {"npcs": [], "enemies": []}}
        )
    )

    # LLM: first response should be accepted as-is
    llm_route = mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    )
    llm_route.side_effect = [
        Response(200, json=create_chat_completion_response("Just a normal story.")),
    ]

    # Execute
    initial_state = {
        "session_id": "999",
        "user_input": "Look around",
        "is_npc_turn": False,
        "active_entity_id": "player",
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "EXPLORATION",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player", "chest"]},
    }

    engine = get_test_engine(mock_db_handler)
    final_state = await engine.graph.ainvoke(initial_state)

    # Verify
    assert final_state["narrative"] == "Just a normal story."
    assert llm_route.call_count == 1


@pytest.mark.asyncio
async def test_pipeline_halts_on_state_error(mock_external_services, mock_db_handler):
    """
    Precision Test 3: Error Handling
    State Manager returns 500 Error.
    Expectation: Pipeline raises exception and stops (does not generate narrative).
    """
    mock_external_services.routes.clear()

    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "500",
                    "scenario_id": "1",
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
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"
    ).mock(
        return_value=Response(
            200,
            json={
                "is_triggered": False,
                "reason": "Scenario Check",
                "next_act_id": None,
                "next_seq_id": None,
                "suggested_narration": None,
            },
        )
    )

    # State Manager Fails
    mock_external_services.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(500, json={"error": "Database unavailable"})
    )

    # Mock get_state as well
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/[^/]+$"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "500",
                    "world_snapshot": {"player_id": "player"},
                },
            },
        )
    )
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*/sequence/details"
    ).mock(
        return_value=Response(
            200, json={"status": "success", "data": {"npcs": [], "enemies": []}}
        )
    )

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
        "session_id": "500",
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
    engine = get_test_engine(mock_db_handler)

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

    from gm.exceptions import PipelineError

    engine.state_client.commit = MagicMock(side_effect=error)

    with pytest.raises(PipelineError) as excinfo:
        await engine.graph.ainvoke(initial_state)

    assert excinfo.value.original_error == error

    # Verify LLM was not called
    assert llm_route.call_count == 0


@pytest.mark.asyncio
async def test_npc_turn_workflow(mock_external_services, mock_db_handler):
    """
    Precision Test 4: NPC Turn Workflow
    Verifies that the NPC turn logic generates input and proceeds through the pipeline.
    """
    mock_external_services.routes.clear()

    # Rule Check
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "777",
                    "scenario_id": "1",
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
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"
    ).mock(
        return_value=Response(
            200,
            json={
                "is_triggered": False,
                "reason": "NPC Scenario Check",
                "next_act_id": None,
                "next_seq_id": None,
                "suggested_narration": None,
            },
        )
    )

    # State Commit
    mock_external_services.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(200, json={"commit_id": "commit_npc_test"})
    )

    # Mock get_state as well
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/[^/]+$"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "777",
                    "world_snapshot": {"player_id": "player"},
                },
            },
        )
    )
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*/sequence/details"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "npcs": [
                        {"id": "npc_1", "name": "NPC 1", "scenario_entity_id": "npc_1"}
                    ],
                    "enemies": [],
                },
            },
        )
    )

    llm_chat_route = mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    )
    llm_chat_route.side_effect = [
        Response(200, json=create_chat_completion_response("npc_1")),  # Select Actor
        Response(
            200,
            json=create_chat_completion_response(
                '{"action":"The NPC attacks!","dialogue":"For the queen!"}'
            ),
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
        "session_id": "777",
        "user_input": "",  # Empty initially
        "is_npc_turn": True,
        "active_entity_id": "",  # Pending selection
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "COMBAT",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player", "npc_1"]},
    }

    engine = get_test_engine(mock_db_handler)
    final_state = await engine.graph.ainvoke(initial_state)

    # Verify
    assert final_state["active_entity_id"] == "npc_1"
    assert final_state["user_input"] == "The NPC attacks!"
    assert final_state.get("npc_dialogue") == "For the queen!"
    assert final_state["narrative"] == "Narrative: The NPC attacks aggressively!"
    assert llm_chat_route.call_count == 3
