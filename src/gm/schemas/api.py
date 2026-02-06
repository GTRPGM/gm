from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field


class TurnOutputType(str, Enum):
    NPC = "npc"
    NARRATION = "narration"


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
    active_entity_id: Optional[str] = Field(
        "player", description="현재 행동을 수행한 엔티티 ID"
    )
    active_entity_name: Optional[str] = Field(
        None, description="현재 행동 엔티티의 표시 이름"
    )
    output_type: TurnOutputType = Field(
        ..., description="출력 주체 타입 (npc 또는 narration)"
    )
    is_npc_turn: bool = Field(False, description="NPC/환경 턴 여부")
    npc_turn: Optional["GameTurnResponse"] = Field(
        None, description="연쇄적으로 발생한 NPC 턴 결과"
    )


class SessionSummaryRequest(BaseModel):
    session_id: str = Field(..., description="세션 UUID")


class SessionSummaryResponse(BaseModel):
    session_id: str = Field(..., description="세션 UUID")
    summary: str = Field(..., description="요약 나레이션")


class HistoryEntry(BaseModel):
    session_id: str = Field(..., description="세션 UUID")
    act_id: Optional[str] = Field(None, description="현재 ACT ID")
    sequence_id: Optional[str] = Field(None, description="현재 시퀀스 ID")
    sequence_type: Optional[str] = Field(None, description="시퀀스 타입")
    sequence_seq: Optional[int] = Field(None, description="시퀀스 진행 순번")
    turn_seq: int = Field(..., description="세션 내 턴 순번")
    active_entity_id: Optional[str] = Field(None, description="행동 엔티티 ID")
    user_input: Optional[str] = Field(None, description="입력 텍스트")
    narrative: str = Field(..., description="결과 나레이션")
    created_at: Optional[str] = Field(None, description="생성 시각")


class SystemReconnectResponse(BaseModel):
    status: str = Field(..., description="재연결 처리 상태")
    message: str = Field(..., description="재연결 처리 메시지")


class SystemStatusResponse(BaseModel):
    status: str = Field(..., description="전체 시스템 상태")
    services: Dict[str, str] = Field(..., description="의존 서비스별 상태")


class RootResponse(BaseModel):
    message: str = Field(..., description="서비스 상태 메시지")


class HealthResponse(BaseModel):
    status: str = Field(..., description="헬스체크 상태")
    db: str = Field(..., description="DB 연결 상태")
