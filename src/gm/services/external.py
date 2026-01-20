from typing import Any, Dict

import httpx

from gm.core.config import settings
from gm.schemas.rule import RuleOutcome
from gm.schemas.scenario import ScenarioSuggestion
from gm.schemas.state import EntityDiff


class RuleManagerClient:
    async def get_proposal(self, content: str) -> RuleOutcome:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.RULE_SERVICE_URL}/api/v1/rule/check",
                json={"input_text": content, "context": {}},
            )
            response.raise_for_status()
            return RuleOutcome(**response.json())


class ScenarioManagerClient:
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


class StateManagerClient:
    async def commit(self, turn_id: str, diffs: list[EntityDiff]) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.STATE_SERVICE_URL}/api/v1/state/commit",
                json={
                    "turn_id": turn_id,
                    "diffs": [d.model_dump() for d in diffs],
                },
            )
            response.raise_for_status()
            return response.json()


class LLMGatewayClient:
    async def generate_narrative(
        self, turn_id: str, commit_id: str, input_text: str, outcome: RuleOutcome
    ) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.LLM_GATEWAY_URL}/api/v1/llm/narrative",
                json={
                    "turn_id": turn_id,
                    "commit_id": commit_id,
                    "input_text": input_text,
                    "rule_outcome": outcome.model_dump(),
                },
            )
            response.raise_for_status()
            return response.json()["narrative"]

    async def generate_npc_action(
        self, session_id: str, context: Dict[str, Any]
    ) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.LLM_GATEWAY_URL}/api/v1/llm/npc-action",
                json={"session_id": session_id, "context": context},
            )
            response.raise_for_status()
            return response.json()["action_text"]
