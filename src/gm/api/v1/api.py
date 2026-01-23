from fastapi import APIRouter

from gm.api.v1.endpoints import game, system

api_router = APIRouter()
api_router.include_router(game.router, prefix="/game", tags=["game"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
