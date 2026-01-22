from typing import Any, Dict, List

from gm.db.database import db
from gm.schemas.input import UserInput
from gm.services.graph import turn_pipeline


class GMService:
    def __init__(self):
        pass

    async def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        query = """
            SELECT
                session_id,
                act_id,
                sequence_id,
                sequence_type,
                sequence_seq,
                turn_seq,
                active_entity_id,
                user_input,
                final_output,
                created_at
            FROM play_logs
            WHERE session_id = $1
            ORDER BY turn_seq ASC
        """
        rows = await db.fetch(query, session_id)
        return [dict(row) for row in rows]

    async def process_player_turn(self, user_input: UserInput) -> Dict[str, Any]:
        # 1. Process Player Turn
        player_state = {
            "session_id": user_input.session_id,
            "user_input": user_input.content,
            "is_npc_turn": False,
            # Context defaults
            "active_entity_id": "player",
            "act_id": "act_1",
            "sequence_id": "seq_1",
            "sequence_type": "EXPLORATION",
            "sequence_seq": 1,
            "world_snapshot": {
                "entities": ["player", "goblin_scout", "elder_merchant", "Narrator"],
                "environment": "Dimly lit cavern with dripping water.",
            },
        }

        player_result_state = await turn_pipeline.ainvoke(player_state)

        player_response = {
            "turn_id": player_result_state["turn_id"],
            "narrative": player_result_state["narrative"],
            "commit_id": player_result_state["commit_id"],
        }

        # 2. Automatically Process NPC Turn
        npc_response = await self.process_npc_turn(user_input.session_id)

        # 3. Return Combined Result
        # API Schema might need update if we want to return list.
        # For now, I'll nest the NPC turn in the response.
        player_response["npc_turn"] = npc_response

        return player_response

    async def process_npc_turn(self, session_id: str) -> Dict[str, Any]:
        # NPC 턴인 경우 user_input은 그래프 내부의 generate_npc_input 노드에서 생성됨
        initial_state = {
            "session_id": session_id,
            "user_input": "",  # 그래프 내부에서 생성될 예정
            "is_npc_turn": True,
            # Context defaults
            "active_entity_id": "npc_pending",  # Will be decided in graph
            "act_id": "act_1",
            "sequence_id": "seq_1",
            "sequence_type": "COMBAT",
            "sequence_seq": 1,
            "world_snapshot": {
                "entities": ["player", "goblin_warrior", "goblin_shaman", "Narrator"],
                "environment": "Heat of battle, sparks flying.",
            },
        }

        # 그래프 비동기 실행
        final_state = await turn_pipeline.ainvoke(initial_state)

        return {
            "turn_id": final_state["turn_id"],
            "narrative": final_state["narrative"],
            "commit_id": final_state["commit_id"],
            "active_entity_id": final_state.get("active_entity_id"),  # Return who acted
            "is_npc_turn": True,
        }


gm_service = GMService()
