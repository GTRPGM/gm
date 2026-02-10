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
    import time
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gpt-4",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop"
        }],
    }

@pytest.mark.asyncio
async def test_conflict_resolution_scenario_wins(mock_external_services, mock_db_handler):
    mock_external_services.routes.clear()
    
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "12345",
                "scenario_id": "1",
                "success": True,
                "reason": "OK",
                "suggested": {"diffs": [{"state_entity_id": "player", "diff": {"hp": -10}}], "relations": []},
            }
        })
    )
    mock_external_services.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate").mock(
        return_value=Response(200, json={"status": "success", "data": {"is_triggered": True, "should_end": False, "reason": "C"}})
    )
    mock_external_services.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(200, json={"status": "success", "data": {"commit_id": "c1"}})
    )
    mock_external_services.get(url__regex=f"{settings.STATE_MANAGER_URL}/state/session/12345$").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "12345",
                "world_snapshot": {"player_id": "player"}
            }
        })
    )
    mock_external_services.get(url__regex=f".*/sequence/details$").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {"npcs": [], "enemies": [], "goal": "test"}
        })
    )
    mock_external_services.post(f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions").mock(
        return_value=Response(200, json=create_chat_completion_response("Conflict resolved."))
    )

    initial_state = {
        "session_id": "12345", "user_input": "Attack", "is_npc_turn": False,
        "active_entity_id": "player", "act_id": "act_1", "sequence_id": "seq_1",
        "sequence_type": "COMBAT", "sequence_seq": 1,
    }

    engine = get_test_engine(mock_db_handler)
    final_state = await engine.graph.ainvoke(initial_state)

    assert any(d.entity_id == "player" and d.diff["hp"] == -10 for d in final_state["final_diffs"])


@pytest.mark.asyncio
async def test_narrative_retry_logic(mock_external_services, mock_db_handler):
    mock_external_services.routes.clear()
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "999",
                "scenario_id": "1",
                "success": True,
                "reason": "OK",
                "suggested": {"diffs": [], "relations": []}
            }
        })
    )
    mock_external_services.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate").mock(
        return_value=Response(200, json={"status": "success", "data": {"is_triggered": True, "suggested_narration": "SECRET"}})
    )
    mock_external_services.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(200, json={"status": "success", "data": {"commit_id": "c2"}})
    )
    mock_external_services.get(url__regex=f"{settings.STATE_MANAGER_URL}/state/session/999$").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "999",
                "world_snapshot": {"player_id": "player"}
            }
        })
    )
    mock_external_services.get(url__regex=f".*/sequence/details$").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {"npcs": [], "enemies": [], "goal": "test"}
        })
    )
    llm_route = mock_external_services.post(f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions")
    llm_route.side_effect = [Response(200, json=create_chat_completion_response("Just a normal story."))]

    initial_state = {
        "session_id": "999", "user_input": "Look around", "is_npc_turn": False,
        "active_entity_id": "player", "act_id": "act_1", "sequence_id": "seq_1",
        "sequence_type": "EXPLORATION", "sequence_seq": 1,
    }

    engine = get_test_engine(mock_db_handler)
    final_state = await engine.graph.ainvoke(initial_state)

    assert final_state["narrative"] == "Just a normal story."
    assert llm_route.call_count == 1