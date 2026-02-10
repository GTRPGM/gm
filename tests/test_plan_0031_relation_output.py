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
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


@pytest.mark.asyncio
async def test_gm_output_relations_to_state_manager(
    mock_external_services, mock_db_handler
):
    """
    Test Plan 0031: Verify that GM correctly extracts relations from Rule Engine outcome
    and sends them to State Manager during commit.
    """
    mock_external_services.routes.clear()

    # 1. Rule Engine returns a new relation
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "session-rel-1",
                    "scenario_id": "scenario-1",
                    "phase_type": "DIALOGUE",
                    "reason": "OK",
                    "success": True,
                    "suggested": {
                        "diffs": [],
                        "relations": [
                            {
                                "cause_entity_id": "player-uuid",
                                "effect_entity_id": "npc-uuid",
                                "type": "우호적",
                                "affinity_score": 10,
                            }
                        ],
                    },
                    "value_range": None,
                },
                "message": "OK",
            },
        )
    )

    # 2. Scenario Service
    mock_external_services.post(
        f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"
    ).mock(
        return_value=Response(
            200,
            json={
                "is_triggered": False,
                "reason": "OK",
                "next_act_id": None,
                "next_seq_id": None,
                "suggested_narration": None,
            },
        )
    )

    # 3. State Manager Commit - We want to intercept this!
    commit_route = mock_external_services.post(
        f"{settings.STATE_MANAGER_URL}/state/commit"
    ).mock(return_value=Response(200, json={"commit_id": "commit-rel-1"}))

    # State Manager Get State
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/[^/]+$"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "session-rel-1",
                    "world_snapshot": {
                        "player_id": "player-uuid",
                        "npcs": [{"id": "npc-uuid", "name": "NPC"}],
                    },
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
    # act details mock
    mock_external_services.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*/act/details"
    ).mock(return_value=Response(200, json={"status": "success", "data": {}}))

    # LLM
    mock_external_services.post(
        f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions"
    ).mock(
        return_value=Response(200, json=create_chat_completion_response("Narrative"))
    )

    # Execute
    initial_state = {
        "session_id": "session-rel-1",
        "user_input": "Hello NPC",
        "is_npc_turn": False,
        "active_entity_id": "player-uuid",
        "act_id": "act_1",
        "sequence_id": "seq_1",
        "sequence_type": "DIALOGUE",
        "sequence_seq": 1,
        "world_snapshot": {"entities": ["player-uuid", "npc-uuid"]},
    }

    engine = get_test_engine(mock_db_handler)
    await engine.graph.ainvoke(initial_state)

    # Verify Commit Payload
    assert commit_route.called
    import json

    payload = json.loads(commit_route.calls.last.request.content)

    update_data = payload.get("update", {})
    relations = update_data.get("relations", [])

    assert len(relations) == 1
    rel = relations[0]
    assert rel["cause_entity_id"] == "player-uuid"
    assert rel["effect_entity_id"] == "npc-uuid"
    assert rel["type"] == "우호적"
    assert rel["affinity_score"] == 10
