from fastapi import APIRouter, HTTPException

from gm.schemas.input import UserInput
from gm.services.gm_service import gm_service

router = APIRouter()


@router.post("/turn")
async def process_turn(user_input: UserInput):
    try:
        result = await gm_service.process_player_turn(user_input)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error") from e
