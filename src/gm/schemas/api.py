from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TurnOutputType(str, Enum):
    NPC = "npc"
    NARRATION = "narration"


class TurnOutputKind(str, Enum):
    NARRATION = "narration"
    DIALOGUE = "dialogue"


class SegmentType(str, Enum):
    NARRATION = "narration"
    DIALOGUE = "dialogue"
    ACTION = "action"


class Segment(BaseModel):
    type: SegmentType = Field(
        ..., description="세그먼트 타입 (action/dialogue/narration)"
    )
    role: str = Field(..., description="출력 주체 표시 이름(예: narrator, NPC 이름)")
    content: str = Field(..., description="세그먼트 텍스트")


class ActorType(str, Enum):
    PLAYER = "player"
    NARRATOR = "narrator"
    NPC = "npc"
    ENEMY = "enemy"
    UNKNOWN = "unknown"


class TurnOutput(BaseModel):
    kind: TurnOutputKind = Field(..., description="출력 종류 (나레이션/대사)")
    text: str = Field(..., description="출력 텍스트")
    actor_type: ActorType = Field(..., description="출력 주체 타입")
    actor_id: Optional[str] = Field(None, description="출력 주체 ID")
    actor_name: Optional[str] = Field(None, description="출력 주체 표시 이름")


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
    action: Optional[str] = Field(
        None,
        description=(
            "이번 턴의 행동(action) 원문. "
            "플레이어 턴이면 사용자 입력, NPC/적 턴이면 생성된 행동 텍스트. "
            "대사(dialogue)와 분리되어 반환된다."
        ),
    )
    narrative: str = Field(..., description="생성된 서사 내용")
    dialogue: Optional[str] = Field(
        None,
        description=("NPC/적의 직접 발화(대사). action과는 별개로 분리되어 반환된다."),
    )
    outputs: List[TurnOutput] = Field(
        default_factory=list,
        description=(
            "나레이션/대사 등 출력 조각 리스트. "
            "클라이언트는 kind로 구분해서 렌더링할 수 있다."
        ),
    )
    segments: List[Segment] = Field(
        default_factory=list,
        description=(
            "구조화 출력 세그먼트 리스트. "
            "대사(dialogue)와 나레이션(narration)을 명확히 분리해 반환한다."
        ),
    )
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


class GameTurnResponseV2(BaseModel):
    """
    Segments-only 응답 모델.
    - narrative/dialogue/outputs 등 레거시 필드는 제거하고, segments만으로 렌더링을 강제
    """

    turn_id: str = Field(..., description="턴 식별자 (session_id:seq)")
    commit_id: Optional[str] = Field(None, description="상태 확정 ID")
    active_entity_id: Optional[str] = Field(None, description="행동 엔티티 ID")
    active_entity_name: Optional[str] = Field(None, description="행동 엔티티 이름")
    output_type: str = Field("narration", description="출력 타입 (npc/narration)")
    is_npc_turn: bool = Field(False, description="NPC/환경 턴 여부")
    current_act_id: Optional[str] = Field(None, description="턴 이후 현재 ACT ID")
    current_sequence_id: Optional[str] = Field(
        None, description="턴 이후 현재 시퀀스 ID"
    )
    session_status: Optional[str] = Field(
        None, description="턴 이후 세션 status (active/ended 등)"
    )
    is_session_ended: bool = Field(False, description="턴 이후 세션 종료 여부")
    narrative: Optional[str] = Field(None, description="하위 호환성을 위한 전체 서사 텍스트")
    segments: List[Segment] = Field(
        default_factory=list,
        description="구조화 출력 세그먼트 리스트 (action/dialogue/narration).",
    )
    transition: Optional[dict] = Field(
        None,
        description=(
            "ACT/SEQUENCE 전이 정보. "
            "예: {from_act_id, from_sequence_id, to_act_id, to_sequence_id, changed}."
        ),
    )
    npc_turn: Optional["GameTurnResponseV2"] = Field(
        None, description="연쇄적으로 발생한 첫 번째 NPC 턴 결과"
    )
    npc_turns: List["GameTurnResponseV2"] = Field(
        default_factory=list, description="연쇄적으로 발생한 모든 NPC 턴 리스트"
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
