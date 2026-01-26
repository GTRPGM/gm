from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class RuleRequestEntity(BaseModel):
    entity_id: Union[str, int]
    entity_name: str


class RuleRequestRelation(BaseModel):
    cause_entity_id: Union[str, int]
    effect_entity_id: Union[str, int]
    type: str


class RuleCheckRequest(BaseModel):
    session_id: Union[str, int]
    scenario_id: Union[str, int]
    entities: List[RuleRequestEntity]
    relations: List[RuleRequestRelation]
    story: str


class RulesuggestedDiff(BaseModel):
    entity_id: Union[str, int]
    diff: Union[
        str, Dict[str, Any]
    ]  # diff can be string (description) or dict (changes)


class RuleSuggestedRelation(BaseModel):
    cause_entity_id: Union[str, int]
    effect_entity_id: Union[str, int]
    type: str


class RuleSuggestion(BaseModel):
    diffs: List[RulesuggestedDiff] = Field(default_factory=list)
    relations: List[RuleSuggestedRelation] = Field(default_factory=list)


class RuleOutcomeData(BaseModel):
    session_id: Union[str, int]
    scenario_id: Union[str, int]
    phase_type: str = "Unspecified"
    reason: str
    success: bool
    suggested: RuleSuggestion
    value_range: Optional[Union[float, Dict[str, float]]] = None


class RuleCheckResponse(BaseModel):
    status: str
    data: RuleOutcomeData
    message: str


class RuleOutcome(RuleOutcomeData):
    @property
    def description(self) -> str:
        return self.reason

    @property
    def suggested_diffs(self) -> List[Dict[str, Any]]:
        # Map new diff structure to old List[Dict] format if needed by GameEngine
        normalized = []
        for d in self.suggested.diffs:
            diff_val = d.diff
            if isinstance(diff_val, str):
                diff_val = {"_description": diff_val}

            normalized.append({"entity_id": str(d.entity_id), "diff": diff_val})
        return normalized
