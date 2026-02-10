from unittest.mock import AsyncMock

import pytest

from gm.core.engine.game_engine import GameEngine
from gm.schemas.rule_engine import RuleOutcome, RuleSuggestedRelation, RuleSuggestion
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion


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
async def test_gm_internal_resolve_logic_with_delta(game_engine):
    """
    GM 내부의 resolve_conflicts 로직 검증:
    룰엔진의 변화량(Delta)과 시나리오 서비스의 교정치를 혼합했을 때
    최종 커밋 페이로드가 정확히 생성되는지 확인
    """

    # 1. 룰엔진 출력: 호감도 +7 변화량 제안
    mock_rule_outcome = RuleOutcome(
        session_id="s1",
        scenario_id="sc1",
        success=True,
        reason="대화 성공",
        suggested=RuleSuggestion(
            diffs=[
                {"state_entity_id": "player", "diff": {"hp": -1}}
            ],  # 플레이어 HP 1 감소
            relations=[
                RuleSuggestedRelation(
                    cause_entity_id="player",
                    effect_entity_id="npc-1",
                    type="우호적",
                    affinity_score=7,  # 변화량 +7
                    quantity=None,
                )
            ],
        ),
    )

    # 2. 시나리오 서비스 출력: 플레이어 HP 감소 무효화 (0으로 교정)
    mock_scenario_suggestion = ScenarioSuggestion(
        constraint_type=ScenarioConstraintType.MANDATORY,
        description="성스러운 가호로 피해를 입지 않음",
        correction_diffs=[{"entity_id": "player", "diff": {"hp": 0}}],
        next_act_id=None,
        next_seq_id=None,
        should_end=False,
    )

    state = {
        "rule_outcome": mock_rule_outcome,
        "scenario_suggestion": mock_scenario_suggestion,
        "final_diffs": [],
        "final_relations": [],
    }

    # 3. GM 내부 로직 실행
    result = await game_engine.resolve_conflicts(state)

    # --- 검증 1: 관계(Relation) 처리 ---
    assert "final_relations" in result
    final_rels = result["final_relations"]
    assert len(final_rels) == 1
    assert final_rels[0].affinity_score == 7  # 변화량이 그대로 유지되어야 함
    assert final_rels[0].type == "우호적"

    # --- 검증 2: 엔티티 상태(Diff) 병합 처리 ---
    # 룰엔진은 -1을 제안했지만 시나리오가 0으로 교정했으므로 최종은 0이어야 함
    final_diffs = result["final_diffs"]
    player_diff = next((d for d in final_diffs if d.entity_id == "player"), None)
    assert player_diff is not None
    assert player_diff.diff["hp"] == 0  # 시나리오 서비스의 교정이 반영되었는지 확인

    print(
        "\n[SUCCESS] GM internal logic correctly resolved conflicts and maintained deltas."
    )


@pytest.mark.asyncio
async def test_gm_client_mapping_logic():
    """
    RuleManagerHTTPClient가 룰엔진의 복잡한 JSON 응답을
    내부 Pydantic 모델로 유실 없이 파싱하는지 검증
    """
    from gm.plugins.external.http_client import RuleManagerHTTPClient

    client = RuleManagerHTTPClient()

    # 룰엔진의 실제 예상 응답 구조 (Nested suggested.relations)
    raw_response = {
        "status": "success",
        "data": {
            "session_id": "s1",
            "scenario_id": "sc1",
            "phase_type": "대화",
            "reason": "테스트",
            "success": True,
            "suggested": {
                "diffs": [],
                "relations": [
                    {
                        "cause_entity_id": "p1",
                        "effect_entity_id": "n1",
                        "type": "우호적",
                        "affinity_score": 10,
                    }
                ],
            },
        },
    }

    # 내부 _unwrap 및 모델 생성 로직 모방
    from gm.plugins.external.http_client import _unwrap_response_data

    unwrapped = _unwrap_response_data(raw_response)
    outcome = RuleOutcome(**unwrapped)

    assert outcome.suggested.relations[0].affinity_score == 10
    assert outcome.suggested.relations[0].type == "우호적"
