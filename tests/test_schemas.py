import pytest
from pydantic import ValidationError

from gm.schemas.rule import RuleOutcome
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion
from gm.schemas.state import EntityDiff, StateCommitRequest


def test_rule_outcome_validation():
    # 정상 케이스
    data = {
        "description": "성공적인 공격",
        "success": True,
        "suggested_diffs": [{"hp": -10}],
        "value_range": {"min": 1, "max": 20},
    }
    outcome = RuleOutcome(**data)
    assert outcome.success is True
    assert outcome.suggested_diffs[0]["hp"] == -10

    # 필수 필드 누락 (description)
    with pytest.raises(ValidationError):
        RuleOutcome(success=True)


def test_scenario_suggestion_validation():
    data = {
        "constraint_type": "mandatory",
        "description": "시나리오상 이 문은 열릴 수 없습니다.",
        "correction_diffs": [{"is_locked": True}],
        "narrative_slot": "잠긴 문에 대한 묘사",
    }
    suggestion = ScenarioSuggestion(**data)
    assert suggestion.constraint_type == ScenarioConstraintType.MANDATORY
    assert suggestion.narrative_slot == "잠긴 문에 대한 묘사"


def test_state_commit_request_validation():
    diffs = [
        EntityDiff(entity_id="player_1", diff={"hp": 90}),
        EntityDiff(entity_id="door_1", diff={"status": "open"}),
    ]
    request = StateCommitRequest(
        turn_id="session_1:1", diffs=diffs, description="테스트 커밋"
    )
    assert len(request.diffs) == 2
    assert request.diffs[0].entity_id == "player_1"
