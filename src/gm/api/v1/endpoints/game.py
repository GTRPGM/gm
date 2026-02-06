import logging
from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from gm.core.deps import get_game_engine
from gm.core.engine.game_engine import GameEngine
from gm.schemas.api import GameTurnResponse, NpcTurnInput, UserInput
from gm.exceptions import PipelineError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/turn", response_model=GameTurnResponse)
async def process_turn(
    user_input: UserInput, engine: Annotated[GameEngine, Depends(get_game_engine)]
) -> Any:
    try:
        result = await engine.process_player_turn(user_input)
        return result
    except PipelineError as e:
        logger.error(f"Pipeline failure: {e.to_dict()}")
        raise HTTPException(
            status_code=502,  # Bad Gateway for backend service failures
            detail=e.to_dict(),
        ) from e
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500, detail={"error_type": "UnexpectedError", "message": str(e)}
        ) from e


@router.post("/npc-turn", response_model=GameTurnResponse)
async def process_npc_turn(
    input_data: NpcTurnInput, engine: Annotated[GameEngine, Depends(get_game_engine)]
) -> Any:
    try:
        result = await engine.process_npc_turn(input_data.session_id)
        return result
    except PipelineError as e:
        raise HTTPException(status_code=502, detail=e.to_dict()) from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error_type": "UnexpectedError", "message": str(e)}
        ) from e


@router.get("/history/{session_id}", response_model=List[Dict[str, Any]])
async def get_history(
    session_id: str, engine: Annotated[GameEngine, Depends(get_game_engine)]
) -> List[Dict[str, Any]]:
    try:
        history = await engine.get_session_history(session_id)
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/summary", response_model=Dict[str, str])
async def get_session_summary(
    payload: Dict[str, str], engine: Annotated[GameEngine, Depends(get_game_engine)]
) -> Dict[str, str]:
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    
    try:
        summary = await engine.generate_summary(session_id)
        return {"session_id": session_id, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
