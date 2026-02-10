from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from gm.core.engine.game_engine import GameEngine
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion

def get_test_engine(db_handler):
    return GameEngine(
        rule_client=RuleManagerHTTPClient(),
        scenario_client=ScenarioManagerHTTPClient(),
        state_client=StateManagerHTTPClient(),
        llm=NarrativeChatModel(),
        db=db_handler,
    )

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
