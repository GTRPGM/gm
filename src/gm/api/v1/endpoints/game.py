from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from gm.schemas.input import NpcTurnInput, UserInput
from gm.services.gm_service import gm_service

router = APIRouter()


@router.post("/turn")
async def process_turn(user_input: UserInput):
    try:
        result = await gm_service.process_player_turn(user_input)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error") from e


@router.post("/npc-turn")
async def process_npc_turn(input_data: NpcTurnInput):
    try:
        result = await gm_service.process_npc_turn(input_data.session_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error") from e


@router.get("/history/{session_id}", response_model=List[Dict[str, Any]])
async def get_history(session_id: str):
    try:
        history = await gm_service.get_session_history(session_id)
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
