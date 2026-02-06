from typing import Any, Dict

from pydantic import BaseModel, Field


class EntityDiff(BaseModel):
    """엔티티별 변경사항 (State Manager 및 내부 로직 공용)"""

    entity_id: str = Field(..., description="엔티티 식별자")
    diff: Dict[str, Any] = Field(..., description="변경될 필드와 값")
