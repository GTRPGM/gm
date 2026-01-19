from typing import Any, Dict, List

from pydantic import BaseModel, Field


class NarrativeRequest(BaseModel):
    turn_id: str
    commit_id: str
    input_text: str
    final_outcome: Dict[str, Any]  # GM이 확정한 최종 결과
    narrative_slots: List[str] = Field(default_factory=list)


class NarrativeResponse(BaseModel):
    content: str
