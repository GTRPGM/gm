from fastapi import APIRouter

from gm.api.v1.endpoints import game

api_router = APIRouter()
api_router.include_router(game.router, prefix="/game", tags=["game"])
