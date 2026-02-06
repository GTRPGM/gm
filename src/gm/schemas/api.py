from typing import Optional

from pydantic import BaseModel, Field


class UserInput(BaseModel):
    """플레이어 턴 진행을 위한 입력 모델"""

    session_id: str = Field(..., description="세션 UUID")
    content: str = Field(..., description="사용자 자연어 입력")


class NpcTurnInput(BaseModel):
    """NPC/환경 턴 진행을 위한 입력 모델"""

    session_id: str = Field(..., description="세션 UUID")


class GameTurnResponse(BaseModel):
    """턴 진행 결과 응답 모델"""

    turn_id: str = Field(..., description="턴 식별자 (session_id:seq)")
    narrative: str = Field(..., description="생성된 서사 내용")
    commit_id: Optional[str] = Field(None, description="상태 확정 ID")
    active_entity_id: Optional[str] = Field("player", description="현재 행동을 수행한 엔티티 ID")
    is_npc_turn: bool = Field(False, description="NPC/환경 턴 여부")
    npc_turn: Optional["GameTurnResponse"] = Field(None, description="연쇄적으로 발생한 NPC 턴 결과")
