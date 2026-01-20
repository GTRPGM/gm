from typing import Any, Dict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from gm.core.config import settings
from gm.schemas.rule import RuleOutcome
from gm.schemas.scenario import ScenarioSuggestion
from gm.schemas.state import EntityDiff

# 기본 재시도 설정: 예외 발생 시 최대 3회 시도, 지수 백오프 적용 (최소 0.1초, 최대 2초)
retry_policy = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
    retry=retry_if_exception_type(httpx.RequestError),
    reraise=True,
)


class RuleManagerClient:
    @retry_policy
    async def get_proposal(self, content: str) -> RuleOutcome:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.RULE_SERVICE_URL}/api/v1/rule/check",
                json={"input_text": content, "context": {}},
            )
            response.raise_for_status()
            return RuleOutcome(**response.json())


class ScenarioManagerClient:
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


class StateManagerClient:
    @retry_policy
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
    @retry_policy
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

    @retry_policy
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
