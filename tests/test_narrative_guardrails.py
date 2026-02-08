from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gm.core.engine.game_engine import GameEngine
from gm.schemas.rule_engine import RuleOutcome, RuleSuggestion
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion


def _build_engine():
    rule_client = AsyncMock()
    scenario_client = AsyncMock()
    state_client = AsyncMock()
    llm = AsyncMock()
    db = AsyncMock()
    return GameEngine(rule_client, scenario_client, state_client, llm, db), state_client


@pytest.mark.asyncio
async def test_generate_narrative_retries_on_terminal_claim_with_live_enemies():
    engine, state_client = _build_engine()

    state_client.get_state.return_value = {"current_sequence_id": "seq-6"}
    state_client.get_sequence_details.return_value = {
        "sequence_id": "seq-6",
        "enemies": [
            {
                "assigned_sequence_id": "seq-6",
                "current_hp": 12,
                "is_defeated": False,
                "name": "warden",
            }
        ],
    }
    engine._fetch_history = AsyncMock(return_value=[])

    first = MagicMock()
    first.content = "핵심 적을 쓰러뜨렸고 모험은 끝이 났다."
    second = MagicMock()
    second.content = "적의 압박을 버티며 전투를 이어간다."

    with patch(
        "gm.core.engine.game_engine.ChatPromptTemplate.from_messages"
    ) as mock_prompt_cls:
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(side_effect=[first, second])
        mock_prompt = MagicMock()
        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_cls.return_value = mock_prompt

        state = {
            "session_id": "s1",
            "user_input": "공격한다",
            "active_entity_id": "player",
            "world_snapshot": {"current_sequence_id": "seq-6"},
            "rule_outcome": RuleOutcome(
                session_id="s1",
                scenario_id="scn-1",
                reason="ok",
                success=True,
                suggested=RuleSuggestion(),
            ),
            "scenario_suggestion": ScenarioSuggestion(
                constraint_type=ScenarioConstraintType.ADVISORY,
                description="keep fighting",
                narrative_slot="모험은 끝이 났다.",
                should_end=False,
            ),
        }

        result = await GameEngine.generate_narrative.__wrapped__(engine, state)

    assert result["narrative"] == "적의 압박을 버티며 전투를 이어간다."
    assert "모험은 끝이 났다." not in result["narrative"]
    assert mock_chain.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_generate_narrative_appends_terminal_phrase_when_session_ended():
    engine, state_client = _build_engine()

    state_client.get_state.return_value = {
        "current_sequence_id": "seq-6",
        "status": "ended",
    }
    state_client.get_sequence_details.return_value = {
        "sequence_id": "seq-6",
        "enemies": [
            {
                "assigned_sequence_id": "seq-6",
                "current_hp": 0,
                "is_defeated": True,
                "name": "warden",
            }
        ],
    }
    engine._fetch_history = AsyncMock(return_value=[])

    first = MagicMock()
    first.content = "적을 제압하고 주변을 정리했다."

    with patch(
        "gm.core.engine.game_engine.ChatPromptTemplate.from_messages"
    ) as mock_prompt_cls:
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(side_effect=[first])
        mock_prompt = MagicMock()
        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_cls.return_value = mock_prompt

        state = {
            "session_id": "s1",
            "user_input": "마무리한다",
            "active_entity_id": "player",
            "world_snapshot": {"current_sequence_id": "seq-6"},
            "rule_outcome": RuleOutcome(
                session_id="s1",
                scenario_id="scn-1",
                reason="ok",
                success=True,
                suggested=RuleSuggestion(),
            ),
            "scenario_suggestion": ScenarioSuggestion(
                constraint_type=ScenarioConstraintType.MANDATORY,
                description="terminal",
                should_end=True,
            ),
        }

        result = await GameEngine.generate_narrative.__wrapped__(engine, state)

    assert "모험은 끝이 났다." in result["narrative"]
    assert mock_chain.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_generate_narrative_sanitizes_finality_claims_when_live_enemies():
    engine, state_client = _build_engine()

    state_client.get_state.return_value = {"current_sequence_id": "seq-6"}
    state_client.get_sequence_details.return_value = {
        "sequence_id": "seq-6",
        "enemies": [
            {
                "assigned_sequence_id": "seq-6",
                "current_hp": 10,
                "is_defeated": False,
                "name": "warden",
            }
        ],
    }
    engine._fetch_history = AsyncMock(return_value=[])

    bad = MagicMock()
    bad.content = "마지막 남은 핵심 적을 처치하고 승리를 확신한다."

    with patch(
        "gm.core.engine.game_engine.ChatPromptTemplate.from_messages"
    ) as mock_prompt_cls:
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(side_effect=[bad, bad, bad])
        mock_prompt = MagicMock()
        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_cls.return_value = mock_prompt

        state = {
            "session_id": "s1",
            "user_input": "공격한다",
            "active_entity_id": "player",
            "world_snapshot": {"current_sequence_id": "seq-6"},
            "rule_outcome": RuleOutcome(
                session_id="s1",
                scenario_id="scn-1",
                reason="ok",
                success=True,
                suggested=RuleSuggestion(),
            ),
            "scenario_suggestion": ScenarioSuggestion(
                constraint_type=ScenarioConstraintType.ADVISORY,
                description="keep fighting",
                should_end=False,
            ),
        }

        result = await GameEngine.generate_narrative.__wrapped__(engine, state)

    assert "전투는 아직 끝나지 않았고 적의 위협이 남아 있다." in result["narrative"]
    assert "마지막 남은 핵심 적" not in result["narrative"]
    assert "승리를 확신" not in result["narrative"]
    assert mock_chain.ainvoke.await_count == 3
