from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScenarioConstraintType(str, Enum):
    MANDATORY = "mandatory"
    ADVISORY = "advisory"


class ScenarioSuggestion(BaseModel):
    """Scenario Service 제안 모델"""

    constraint_type: ScenarioConstraintType
    description: str
    correction_diffs: List[Dict[str, Any]] = Field(default_factory=list)
    narrative_slot: Optional[str] = Field(None, description="서술 필수 포함 요소")
    next_act_id: Optional[str] = Field(None, description="이동할 다음 액트 ID")
    next_seq_id: Optional[str] = Field(None, description="이동할 다음 시퀀스 ID")
    should_end: bool = Field(False, description="세션 종료 필요 여부")
