from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScenarioConstraintType(str, Enum):
    MANDATORY = "mandatory"  # 반드시 지켜야 함
    ADVISORY = "advisory"  # 권장


class ScenarioCheckRequest(BaseModel):
    input_text: str
    rule_outcome: Dict[str, Any]  # Rule Manager의 결과


class ScenarioSuggestion(BaseModel):
    constraint_type: ScenarioConstraintType
    description: str
    # 시나리오가 제안하는 보정값
    correction_diffs: List[Dict[str, Any]] = Field(default_factory=list)
    narrative_slot: Optional[str] = Field(
        None, description="서술에 포함되어야 할 필수 요소"
    )
