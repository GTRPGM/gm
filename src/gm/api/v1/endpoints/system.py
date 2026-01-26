import asyncio
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends

from gm.core.deps import get_game_engine
from gm.core.engine.game_engine import GameEngine

router = APIRouter()


@router.get("/status")
async def check_system_status(
    engine: Annotated[GameEngine, Depends(get_game_engine)],
) -> Dict[str, Any]:
    """
    Checks the health of all dependent services:
    - Rule Manager
    - Scenario Manager
    - State Manager
    - LLM Gateway
    """

    # Access clients via the engine
    rule_client = engine.rule_client
    scenario_client = engine.scenario_client
    state_client = engine.state_client
    llm_client = engine.llm

    results = {
        "rule_manager": "unknown",
        "scenario_manager": "unknown",
        "state_manager": "unknown",
        "llm_gateway": "unknown",
    }

    # Parallel execution
    async def check_service(name: str, client: Any):
        try:
            is_healthy = await client.check_health()
            results[name] = "ok" if is_healthy else "error"
        except Exception as e:
            results[name] = f"error: {str(e)}"

    await asyncio.gather(
        check_service("rule_manager", rule_client),
        check_service("scenario_manager", scenario_client),
        check_service("state_manager", state_client),
        check_service("llm_gateway", llm_client),
    )

    overall_status = "ok" if all(v == "ok" for v in results.values()) else "degraded"

    return {"status": overall_status, "services": results}
