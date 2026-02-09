from unittest.mock import AsyncMock

import pytest

from gm.core.engine.game_engine import GameEngine
from gm.schemas.common import RelationDiff
from gm.schemas.rule_engine import RuleOutcome, RuleSuggestedRelation, RuleSuggestion


@pytest.fixture
def game_engine():
    return GameEngine(
        rule_client=AsyncMock(),
        scenario_client=AsyncMock(),
        state_client=AsyncMock(),
        llm=AsyncMock(),
        db=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_resolve_conflicts_creates_relations(game_engine):
    # Setup
    state = {
        "session_id": "test_session",
        "turn_id": "test_turn",
        "world_snapshot": {},
        "scenario_suggestion": AsyncMock(
            correction_diffs=[], next_act_id=None, next_seq_id=None, should_end=False
        ),
        "rule_outcome": RuleOutcome(
            session_id="test_session",
            scenario_id="test_scenario",
            success=True,
            reason="test",
            suggested=RuleSuggestion(
                diffs=[],
                relations=[
                    RuleSuggestedRelation(
                        cause_entity_id="player",
                        effect_entity_id="npc-1",
                        type="NEUTRAL",
                        affinity_score=10,
                        quantity=None,
                    )
                ],
            ),
        ),
    }

    # Execute
    result = await game_engine.resolve_conflicts(state)

    # Verify
    assert "final_relations" in result
    relations = result["final_relations"]
    assert len(relations) == 1
    assert isinstance(relations[0], RelationDiff)
    assert relations[0].cause_entity_id == "player"
    assert relations[0].effect_entity_id == "npc-1"
    assert relations[0].type == "NEUTRAL"
    assert relations[0].affinity_score == 10


@pytest.mark.asyncio
async def test_commit_state_passes_relations(game_engine):
    # Setup
    state = {
        "session_id": "test_session",
        "turn_id": "test_turn",
        "final_diffs": [],
        "final_relations": [
            RelationDiff(
                cause_entity_id="player",
                effect_entity_id="npc-1",
                type="NEUTRAL",
                affinity_score=10,
            )
        ],
    }

    game_engine.state_client.commit.return_value = {"commit_id": "test_commit"}

    # Execute
    await game_engine.commit_state(state)

    # Verify
    game_engine.state_client.commit.assert_called_once()
    call_args = game_engine.state_client.commit.call_args
    assert call_args[0][0] == "test_turn"  # turn_id
    assert call_args[0][1] == []  # diffs

    relations = call_args[0][2]  # relations
    assert len(relations) == 1
    assert relations[0].cause_entity_id == "player"
    assert relations[0].effect_entity_id == "npc-1"
    assert relations[0].affinity_score == 10
