from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EntityDiff(BaseModel):
    entity_id: str
    diff: Dict[str, Any] = Field(..., description="변경될 필드와 값")


class StateCommitRequest(BaseModel):
    turn_id: str
    diffs: List[EntityDiff]
    description: Optional[str] = Field(None, description="커밋 설명 (디버깅용)")


class StateCommitResponse(BaseModel):
    commit_id: str
    status: str = "success"
    timestamp: str


class StateQuery(BaseModel):
    entity_ids: List[str]
    # 추가적인 쿼리 조건
