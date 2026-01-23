from typing import Optional

from gm.core.engine.game_engine import GameEngine
from gm.infra.db.database import db
from gm.plugins.external.http_client import (
    RuleManagerHTTPClient,
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.plugins.llm.adapter import NarrativeChatModel

# Singleton instance
_engine: Optional[GameEngine] = None


def get_game_engine() -> GameEngine:
    global _engine
    if _engine is None:
        _engine = GameEngine(
            rule_client=RuleManagerHTTPClient(),
            scenario_client=ScenarioManagerHTTPClient(),
            state_client=StateManagerHTTPClient(),
            llm=NarrativeChatModel(),
            db=db,
        )
    return _engine
