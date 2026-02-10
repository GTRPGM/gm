import pytest
from unittest.mock import MagicMock
from httpx import Response
from gm.core.config import settings
from gm.core.engine.game_engine import GameEngine
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel
from gm.exceptions import PipelineError

def get_test_engine(db_handler):
    return GameEngine(
        rule_client=RuleManagerHTTPClient(),
        scenario_client=ScenarioManagerHTTPClient(),
        state_client=StateManagerHTTPClient(),
        llm=NarrativeChatModel(),
        db=db_handler,
    )

@pytest.mark.asyncio
async def test_pipeline_halts_on_state_error(mock_external_services, mock_db_handler):
    mock_external_services.routes.clear()
    
    mock_external_services.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "500",
                "scenario_id": "1",
                "success": True,
                "reason": "OK",
                "suggested": {"diffs": [], "relations": []}
            }
        })
    )
    mock_external_services.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate").mock(
        return_value=Response(200, json={"is_triggered": False})
    )
    mock_external_services.get(url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*").mock(
        return_value=Response(200, json={
            "status": "success",
            "data": {
                "session_id": "500",
                "world_snapshot": {
                    "player_id": "player",
                    "enemies": [],
                    "npcs": [],
                    "items": []
                }
            }
        })
    )

    llm_route = mock_external_services.post(f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "no"}}]})
    )

    initial_state = {
        "session_id": "500", "user_input": "Save", "is_npc_turn": False,
        "active_entity_id": "player", "act_id": "a1", "sequence_id": "s1",
        "sequence_type": "MENU", "sequence_seq": 1, "world_snapshot": {"entities": ["player"]},
    }

    engine = get_test_engine(mock_db_handler)
    import httpx
    request = httpx.Request("POST", "http://mock/commit")
    error = httpx.HTTPStatusError("500", request=request, response=httpx.Response(500, request=request))
    engine.state_client.commit = MagicMock(side_effect=error)

    with pytest.raises(PipelineError) as excinfo:
        await engine.graph.ainvoke(initial_state)

    assert excinfo.value.original_error == error
    assert llm_route.call_count == 0
