from typing import Any, Dict, List, Optional, TypedDict

from gm.core.models.rule import RuleOutcome
from gm.core.models.scenario import ScenarioSuggestion
from gm.core.models.state import EntityDiff


class TurnContext(TypedDict, total=False):
    """
    LangGraph의 State로 사용될 턴 컨텍스트.
    TypedDict를 사용하여 LangGraph의 상태 관리 기능과 호환성을 높입니다.
    """

    # --- Input ---
    session_id: str
    user_input: str
    is_npc_turn: bool

    # --- Hierarchy Context ---
    act_id: Optional[str]
    sequence_id: Optional[str]
    sequence_type: Optional[str]  # e.g. 'COMBAT', 'EXPLORATION'
    sequence_seq: Optional[int]  # N-th sequence in Act

    active_entity_id: str  # 'player' or NPC ID

    # --- Processing Data ---
    turn_seq: Optional[int]
    turn_id: Optional[str]

    rule_outcome: Optional[RuleOutcome]
    scenario_suggestion: Optional[ScenarioSuggestion]

    final_diffs: List[EntityDiff]
    commit_id: Optional[str]

    # --- World State ---
    world_snapshot: Optional[Dict[str, Any]]  # e.g. {"entities": [...]}

    # --- Output ---
    narrative: Optional[str]

    # --- Internal/Error ---
    error: Optional[str]
