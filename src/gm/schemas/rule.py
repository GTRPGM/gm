from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RuleCheckRequest(BaseModel):
    input_text: str
    context: Dict[str, Any]  # 현재 상태 일부 등


class RuleOutcome(BaseModel):
    description: str
    success: bool
    # 수치적 결과, 상태 변경 제안 등 포함
    suggested_diffs: List[Dict[str, Any]] = Field(default_factory=list)
    required_entities: List[str] = Field(
        default_factory=list, description="판정에 필요한 추가 엔티티 ID들"
    )

    # 룰 매니저가 제안하는 결과의 범위 (봉투)
    value_range: Optional[Dict[str, float]] = None
