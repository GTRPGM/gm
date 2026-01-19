from typing import Any, Dict

from gm.schemas.rule import RuleOutcome
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion
from gm.schemas.state import EntityDiff


class RuleManagerClient:
    async def get_proposal(self, content: str) -> RuleOutcome:
        # TODO: Implement HTTP call to Rule Manager
        return RuleOutcome(
            description="기본 룰 판정",
            success=True,
            suggested_diffs=[{"entity_id": "dummy", "diff": {"status": "updated"}}],
        )


class ScenarioManagerClient:
    async def get_proposal(
        self, content: str, rule_outcome: RuleOutcome
    ) -> ScenarioSuggestion:
        # TODO: Implement HTTP call to Scenario Manager
        return ScenarioSuggestion(
            constraint_type=ScenarioConstraintType.ADVISORY,
            description="시나리오 영향 없음",
        )


class StateManagerClient:
    async def commit(self, turn_id: str, diffs: list[EntityDiff]) -> Dict[str, Any]:
        # TODO: Implement HTTP call to State Manager
        import uuid

        return {"commit_id": f"commit_{uuid.uuid4().hex[:8]}", "status": "success"}


class LLMGatewayClient:
    async def generate_narrative(
        self, turn_id: str, commit_id: str, input_text: str, outcome: RuleOutcome
    ) -> str:
        # TODO: Implement HTTP call to LLM Gateway
        return f"당신의 행동 '{input_text}'에 대한 결과입니다. (판정: {outcome.description})"
