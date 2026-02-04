import pytest

from gm.core.config import settings
from gm.core.engine.game_engine import GameEngine
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel


@pytest.mark.asyncio
async def test_integration_with_real_mock_service(mock_db_handler, respx_mock):
    """
    진짜 HTTP 클라이언트를 사용하여 실행 중인 Mock 서비스(8100)와 통신하는 통합 테스트.
    DB는 Mock으로 처리함.
    """
    # Allow real requests to localhost
    respx_mock.route(host="localhost").pass_through()

    # Override settings to point to local mock service
    settings.RULE_ENGINE_HOST = "localhost"
    settings.RULE_ENGINE_PORT = 8150
    settings.SCENARIO_SERVICE_HOST = "localhost"
    settings.SCENARIO_SERVICE_PORT = 8140
    settings.STATE_MANAGER_HOST = "localhost"
    settings.STATE_MANAGER_PORT = 8130
    settings.LLM_GATEWAY_HOST = "localhost"
    settings.LLM_GATEWAY_PORT = 8160

    engine = GameEngine(
        rule_client=RuleManagerHTTPClient(),
        scenario_client=ScenarioManagerHTTPClient(),
        state_client=StateManagerHTTPClient(),
        llm=NarrativeChatModel(),
        db=mock_db_handler,
    )

    # 1. State Manager Mocking (DB interaction is mocked, but we need world snapshot)
    # The real StateManagerHTTPClient.get_state currently returns a dummy anyway,
    # but let's make sure it's working.

    # 2. Run Player Turn
    class UserInput:
        session_id = "integration_test_session"
        content = "문을 열고 들어간다."

    # NOTE: process_player_turn automatically triggers NPC turn
    # We expect multiple HTTP calls to localhost:8100
    result = await engine.process_player_turn(UserInput())

    assert "turn_id" in result
    assert "narrative" in result
    assert "commit_id" in result
    assert "npc_turn" in result

    print(f"\n[Integration Test] Narrative: {result['narrative']}")
    print(f"[Integration Test] NPC Action: {result['npc_turn']['narrative']}")
