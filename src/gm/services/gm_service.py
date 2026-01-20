from typing import Any, Dict

from gm.schemas.input import UserInput
from gm.services.graph import turn_pipeline


class GMService:
    def __init__(self):
        pass

    async def process_player_turn(self, user_input: UserInput) -> Dict[str, Any]:
        # 초기 상태 구성
        initial_state = {
            "session_id": user_input.session_id,
            "user_input": user_input.content,
            "is_npc_turn": False,
        }

        # 그래프 비동기 실행
        final_state = await turn_pipeline.ainvoke(initial_state)

        return {
            "turn_id": final_state["turn_id"],
            "narrative": final_state["narrative"],
            "commit_id": final_state["commit_id"],
        }

    async def process_npc_turn(self, session_id: str) -> Dict[str, Any]:
        # NPC 턴인 경우 user_input은 그래프 내부의 generate_npc_input 노드에서 생성됨
        initial_state = {
            "session_id": session_id,
            "user_input": "",  # 그래프 내부에서 생성될 예정
            "is_npc_turn": True,
        }

        # 그래프 비동기 실행
        final_state = await turn_pipeline.ainvoke(initial_state)

        return {
            "turn_id": final_state["turn_id"],
            "narrative": final_state["narrative"],
            "commit_id": final_state["commit_id"],
            "is_npc_turn": True,
        }


gm_service = GMService()
