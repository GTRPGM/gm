from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EntityDiff(BaseModel):
    """엔티티별 변경사항 (State Manager 및 내부 로직 공용)"""

    entity_id: str = Field(..., description="엔티티 식별자")
    diff: Dict[str, Any] = Field(..., description="변경될 필드와 값")


class RelationDiff(BaseModel):
    """그래프 관계 변경사항"""

    cause_entity_id: str = Field(..., description="관계 시작 엔티티 ID")
    effect_entity_id: str = Field(..., description="관계 종료 엔티티 ID")
    type: str = Field(..., description="관계 유형")
    affinity_score: Optional[int] = Field(default=None, description="호감도(선택 사항)")
    quantity: Optional[int] = Field(default=None, description="양(선택 사항)")
