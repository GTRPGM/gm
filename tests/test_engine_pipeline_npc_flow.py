import pytest
import time
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
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gpt-4o-mini",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop"
        }],
    }

@pytest.mark.asyncio
async def test_npc_turn_workflow(mock_external_services, mock_db_handler):
    mock_external_services.routes.clear()
    
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "777",
                "scenario_id": "1",
                "success": True,
                "reason": "OK",
                "suggested": {"diffs": [], "relations": []}
            }
        })
    )
    mock_external_services.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate").mock(
        return_value=Response(200, json={"status": "success", "data": {"is_triggered": False}})
    )
    mock_external_services.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(200, json={"status": "success", "data": {"commit_id": "c_npc"}})
    )
    mock_external_services.get(url__regex=f"{settings.STATE_MANAGER_URL}/state/session/777$").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "777",
                "world_snapshot": {"player_id": "player"}
            }
        })
    )
    mock_external_services.get(url__regex=f".*/sequence/details").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "npcs": [{"id": "npc_1", "name": "N1", "scenario_entity_id": "npc_1"}],
                "enemies": [],
                "goal": "test"
            }
        })
    )

    llm_chat_route = mock_external_services.post(f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions")
    llm_chat_route.side_effect = [
        Response(200, json=create_chat_completion_response("npc_1")),  # Select Actor
        Response(200, json=create_chat_completion_response('{"action":"Attacks!"}')),  # Action
        Response(200, json=create_chat_completion_response("The NPC attacks!")),  # Narrative
    ]

    initial_state = {
        "session_id": "777", "user_input": "", "is_npc_turn": True,
        "active_entity_id": "", "act_id": "act_1", "sequence_id": "seq_1",
        "sequence_type": "COMBAT", "sequence_seq": 1,
    }

    engine = get_test_engine(mock_db_handler)
    final_state = await engine.graph.ainvoke(initial_state)

    assert final_state["active_entity_id"] == "npc_1"
    assert final_state["user_input"] == "Attacks!"
    assert llm_chat_route.call_count == 3