from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from gm.schemas.rule import RuleOutcome
from gm.schemas.scenario import ScenarioSuggestion
from gm.schemas.state import EntityDiff


class TurnContext(BaseModel):
    """
    LangGraph의 State로 전환될 파이프라인 컨텍스트.
    턴 처리의 모든 중간 산출물을 담습니다.
    """

    # --- 초기 입력 ---
    session_id: str
    user_input: str
    is_npc_turn: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # --- 처리 단계별 데이터 ---
    turn_seq: Optional[int] = None
    turn_id: Optional[str] = None

    # Node: Rule Check
    rule_outcome: Optional[RuleOutcome] = None

    # Node: Scenario Check
    scenario_suggestion: Optional[ScenarioSuggestion] = None

    # Node: Resolve
    final_diffs: List[EntityDiff] = Field(default_factory=list)

    # Node: Commit
    commit_id: Optional[str] = None

    # Node: Narrative
    narrative: Optional[str] = None

    # --- 결과 및 에러 핸들링 ---
    error: Optional[str] = None
