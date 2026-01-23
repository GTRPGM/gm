from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from gm.core.deps import get_game_engine
from gm.core.engine.game_engine import GameEngine
from gm.core.models.input import NpcTurnInput, UserInput

router = APIRouter()


@router.post("/turn")
async def process_turn(
    user_input: UserInput, engine: Annotated[GameEngine, Depends(get_game_engine)]
) -> Dict[str, Any]:
    try:
        result = await engine.process_player_turn(user_input)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error") from e


@router.post("/npc-turn")
async def process_npc_turn(
    input_data: NpcTurnInput, engine: Annotated[GameEngine, Depends(get_game_engine)]
) -> Dict[str, Any]:
    try:
        result = await engine.process_npc_turn(input_data.session_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error") from e


@router.get("/history/{session_id}", response_model=List[Dict[str, Any]])
async def get_history(
    session_id: str, engine: Annotated[GameEngine, Depends(get_game_engine)]
) -> List[Dict[str, Any]]:
    try:
        history = await engine.get_session_history(session_id)
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
