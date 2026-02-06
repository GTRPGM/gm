from fastapi import Request

from gm.core.engine.game_engine import GameEngine
from gm.infra.db.database import DatabaseHandler
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel


def get_db(request: Request) -> DatabaseHandler:
    """Dependency to get the database instance from app state."""
    return request.app.state.db


def get_game_engine(request: Request) -> GameEngine:
    """Dependency to get a configured GameEngine instance."""
    db = get_db(request)
    return GameEngine(
        rule_client=RuleManagerHTTPClient(),
        scenario_client=ScenarioManagerHTTPClient(),
        state_client=StateManagerHTTPClient(),
        llm=NarrativeChatModel(),
        db=db,
    )
