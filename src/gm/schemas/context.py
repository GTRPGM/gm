from typing import List, Optional, TypedDict

from gm.schemas.rule import RuleOutcome
from gm.schemas.scenario import ScenarioSuggestion
from gm.schemas.state import EntityDiff


class TurnContext(TypedDict):
    """
    LangGraph의 State로 사용될 턴 컨텍스트.
    TypedDict를 사용하여 LangGraph의 상태 관리 기능과 호환성을 높입니다.
    """

    # --- Input ---
    session_id: str
    user_input: str
    is_npc_turn: bool

    # --- Processing Data ---
    turn_seq: Optional[int]
    turn_id: Optional[str]

    rule_outcome: Optional[RuleOutcome]
    scenario_suggestion: Optional[ScenarioSuggestion]

    final_diffs: List[EntityDiff]
    commit_id: Optional[str]

    # --- Output ---
    narrative: Optional[str]

    # --- Internal/Error ---
    error: Optional[str]
