from typing import List, Optional

from pydantic import BaseModel, Field

from gm.schemas.common import EntityDiff


class StateCommitRequest(BaseModel):
    """State Manager 상태 확정 요청"""

    turn_id: str = Field(..., description="턴 식별자 (session_id:seq)")
    diffs: List[EntityDiff] = Field(..., description="변경사항 목록")
    description: Optional[str] = Field(None, description="커밋 설명 (디버깅용)")


class StateCommitResponse(BaseModel):
    """State Manager 상태 확정 응답"""

    commit_id: str
    status: str = "success"
    timestamp: str


class StateQuery(BaseModel):
    """State Manager 상태 조회 쿼리"""

    entity_ids: List[str]
