from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class RuleRequestEntity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    state_entity_id: str
    entity_id: Optional[int] = None
    entity_name: str
    phase_id: int = 1
    entity_type: str = "object"
    quantity: Optional[int] = None


class RuleRequestRelation(BaseModel):
    cause_entity_id: str
    effect_entity_id: str
    type: str


class RuleCheckRequest(BaseModel):
    session_id: str
    scenario_id: str
    locale_id: int = 0
    sequence_type: str = "EXPLORATION"
    actor_id: str = "player"
    entities: List[RuleRequestEntity]
    relations: List[RuleRequestRelation]
    story: str


class RuleSuggestedDiff(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    state_entity_id: str
    diff: Union[str, Dict[str, Any]]


class RuleSuggestedRelation(BaseModel):
    cause_entity_id: str
    effect_entity_id: str
    type: str


class RuleSuggestion(BaseModel):
    diffs: List[RuleSuggestedDiff] = Field(default_factory=list)
    relations: List[RuleSuggestedRelation] = Field(default_factory=list)


class RuleOutcomeData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    session_id: str
    scenario_id: str
    phase_type: str = "Unspecified"
    reason: str
    success: bool
    suggested: RuleSuggestion
    value_range: Optional[Union[float, Dict[str, float]]] = None
    logs: Optional[List[str]] = Field(default_factory=list)


class RuleOutcome(RuleOutcomeData):
    @property
    def description(self) -> str:
        """하위 호환성을 위한 reason의 별칭"""
        return self.reason

    @property
    def suggested_diffs(self) -> List[Dict[str, Any]]:
        normalized = []
        for d in self.suggested.diffs:
            diff_val = d.diff
            if isinstance(diff_val, str):
                diff_val = {"_description": diff_val}
            normalized.append({"entity_id": str(d.state_entity_id), "diff": diff_val})
        return normalized
