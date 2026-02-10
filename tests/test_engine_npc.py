import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
from gm.core.engine.game_engine import GameEngine
from gm.schemas.api import SegmentType

@pytest.mark.asyncio
async def test_npc_turn_priority_and_all_execution(mock_db_handler):
    """
    비즈니스 로직 검증: 
    1. 적(Enemy)이 NPC보다 먼저 행동하는가?
    2. 살아있는 모든 엔티티가 행동을 수행하는가?
    """
    rule_client = AsyncMock()
    scenario_client = AsyncMock()
    state_client = AsyncMock()
    llm = AsyncMock()
    
    engine = GameEngine(rule_client, scenario_client, state_client, llm, mock_db_handler)
    
    # 월드 상태 설정 (유틸리티 필드명과 일치시킴: scenario_entity_id)
    world_state = {
        "status": "active",
        "entities": ["enemy_1", "enemy_2", "npc_1", "npc_2"],
        "enemies": [
            {"scenario_entity_id": "enemy_1", "name": "오크", "current_hp": 10, "is_defeated": False},
            {"scenario_entity_id": "enemy_2", "name": "고블린", "current_hp": 5, "is_defeated": False}
        ],
        "npcs": [
            {"scenario_entity_id": "npc_1", "name": "마을주민A", "is_departed": False},
            {"scenario_entity_id": "npc_2", "name": "마을주민B", "is_departed": False}
        ],
        "current_act_id": "act-1",
        "current_sequence_id": "seq-1"
    }
    
    state_client.get_state.return_value = world_state
    
    execution_order = []
    
    async def mock_process_npc_turn(session_id, force_id=None):
        execution_order.append(force_id)
        return {
            "active_entity_id": force_id,
            "is_session_ended": False,
            "segments": []
        }
    
    engine.process_npc_turn = AsyncMock(side_effect=mock_process_npc_turn)
    engine.graph.ainvoke = AsyncMock(return_value={
        "turn_id": "s1:1",
        "commit_id": "c1",
        "narrative": "플레이어의 공격!",
        "active_entity_id": "player"
    })
    
    user_input = SimpleNamespace(session_id="test_session", content="공격한다")
    result = await engine.process_player_turn(user_input)
    
    # 모든 엔티티가 호출되었는가?
    assert len(execution_order) == 4
    
    # 호출 순서 검증 (적 우선)
    assert execution_order[0] in ["enemy_1", "enemy_2"]
    assert execution_order[1] in ["enemy_1", "enemy_2"]
    assert execution_order[2] in ["npc_1", "npc_2"]
    assert execution_order[3] in ["npc_1", "npc_2"]
    
    print("\n[SUCCESS] NPC turn priority and full execution verified.")

@pytest.mark.asyncio
async def test_npc_turn_halt_on_session_end(mock_db_handler):
    """
    비즈니스 로직 검증: 
    턴 진행 중 세션이 종료되면 다음 엔티티의 행동은 중단되는가?
    """
    state_client = AsyncMock()
    engine = GameEngine(AsyncMock(), AsyncMock(), state_client, AsyncMock(), mock_db_handler)
    
    state_client.get_state.return_value = {
        "status": "active",
        "entities": ["boss", "minion"],
        "enemies": [
            {"scenario_entity_id": "boss", "name": "보스", "current_hp": 100, "is_defeated": False},
            {"scenario_entity_id": "minion", "name": "부하", "current_hp": 10, "is_defeated": False}
        ],
        "npcs": []
    }
    
    async def mock_process_npc_turn(session_id, force_id=None):
        if force_id == "boss":
            return {"is_session_ended": True, "segments": []}
        return {"is_session_ended": False, "segments": []}
        
    engine.process_npc_turn = AsyncMock(side_effect=mock_process_npc_turn)
    engine.graph.ainvoke = AsyncMock(return_value={"turn_id":"1","commit_id":"1","narrative":"ok"})
    
    await engine.process_player_turn(SimpleNamespace(session_id="s1", content="hi"))
    
    assert engine.process_npc_turn.call_count == 1
    assert engine.process_npc_turn.call_args_list[0][0][1] == "boss"
    
    print("\n[SUCCESS] NPC turn sequence halted correctly on session end.")
