from unittest.mock import AsyncMock
import pytest
from gm.core.engine.game_engine import GameEngine
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel
from gm.schemas.rule_engine import RuleOutcome, RuleSuggestion

def get_test_engine(db_handler):
    return GameEngine(
        rule_client=RuleManagerHTTPClient(),
        scenario_client=ScenarioManagerHTTPClient(),
        state_client=StateManagerHTTPClient(),
        llm=NarrativeChatModel(),
        db=db_handler,
    )

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
                {"id": "enemy-state-1", "name": "폐허 늑대"},
                {"id": "enemy-state-2", "name": "산성 슬라임"},
            ]
        },
    }

    result = await engine.check_rule(state)

    assert result["target_selection_mode"] == "random"
    assert result["selected_target_entity_id"] in {"enemy-state-1", "enemy-state-2"}


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
                {"id": "enemy-state-1", "name": "폐허 늑대"},
                {"id": "enemy-state-2", "name": "산성 슬라임"},
            ]
        },
    }

    result = await engine.check_rule(state)

    assert result["target_selection_mode"] == "explicit"
    assert result["selected_target_entity_id"] == "enemy-state-2"
    assert result["selected_target_name"] == "산성 슬라임"
