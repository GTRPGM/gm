from typing import Any, Dict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from gm.core.config import settings
from gm.core.models.rule import (
    RuleCheckResponse,
    RuleOutcome,
    RuleRequestEntity,
)
from gm.core.models.scenario import ScenarioSuggestion
from gm.core.models.state import EntityDiff
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)

# 기본 재시도 설정: 예외 발생 시 최대 3회 시도, 지수 백오프 적용 (최소 0.1초, 최대 2초)
retry_policy = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
    retry=retry_if_exception_type(httpx.RequestError),
    reraise=True,
)


class RuleManagerHTTPClient(RuleManagerPort):
    @retry_policy
    async def get_proposal(self, context: Dict[str, Any]) -> RuleOutcome:
        url = f"{settings.RULE_SERVICE_URL}/api/v1/rule/check"
        print(f"DEBUG: Requesting Rule Check at {url}")

        # Construct payload from context
        session_id = context.get("session_id", "unknown_session")
        user_input = context.get("user_input", "")

        # Map entities from world_snapshot (List[str] -> List[RuleRequestEntity])
        snapshot = context.get("world_snapshot", {})
        entity_names = snapshot.get("entities", [])

        req_entities = []
        for name in entity_names:
            # Assuming ID is same as name for now, or generating dummy ID if needed
            req_entities.append(
                RuleRequestEntity(entity_id=str(name), entity_name=str(name))
            )

        # Relations - currently empty in snapshot usually, but check if exists
        # Assuming snapshot might have 'relations' in future
        req_relations = []

        payload = {
            "session_id": session_id,
            "scenario_id": context.get("scenario_id", 0),  # Default to 0/int
            "entities": [e.model_dump() for e in req_entities],
            "relations": [r.model_dump() for r in req_relations],
            "story": user_input,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

                # Parse response with new schema wrapper
                resp_model = RuleCheckResponse(**response.json())

                return RuleOutcome(**resp_model.data.model_dump())

        except Exception as e:
            print(f"DEBUG: Rule Check Failed: {e}")
            raise e

    async def check_health(self) -> bool:
        url = f"{settings.RULE_SERVICE_URL}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False


class ScenarioManagerHTTPClient(ScenarioManagerPort):
    @retry_policy
    async def get_proposal(
        self, content: str, rule_outcome: RuleOutcome
    ) -> ScenarioSuggestion:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.SCENARIO_SERVICE_URL}/api/v1/scenario/check",
                json={
                    "input_text": content,
                    "rule_outcome": rule_outcome.model_dump(),
                },
            )
            response.raise_for_status()
            return ScenarioSuggestion(**response.json())

    async def check_health(self) -> bool:
        url = f"{settings.SCENARIO_SERVICE_URL}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False


class StateManagerHTTPClient(StateManagerPort):
    # @retry_policy
    async def commit(self, turn_id: str, diffs: list[EntityDiff]) -> Dict[str, Any]:
        # MOCK: State Manager is not ready yet. Return dummy success.
        print(f"DEBUG: [MOCK] State Commit skipped for {turn_id}")
        return {
            "commit_id": f"mock_commit_{turn_id}",
            "status": "success",
            "timestamp": "2026-01-26T00:00:00Z",
        }

    # @retry_policy
    async def get_state(self, session_id: str) -> Dict[str, Any]:
        # MOCK: State Manager is not ready yet. Return dummy snapshot.
        print(f"DEBUG: [MOCK] Returning dummy state for {session_id}")
        return {
            "entities": ["player", "goblin_scout", "ancient_door", "rusty_sword"],
            "relations": [],
            "environment": "Dark Dungeon (Mock State)",
        }

    async def check_health(self) -> bool:
        url = f"{settings.STATE_SERVICE_URL}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False
