from typing import Any, Dict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from gm.core.config import settings
from gm.core.models.rule import RuleOutcome
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
    async def get_proposal(self, content: str) -> RuleOutcome:
        url = f"{settings.RULE_SERVICE_URL}/api/v1/rule/check"
        print(f"DEBUG: Requesting Rule Check at {url}")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json={"input_text": content, "context": {}},
                )
                response.raise_for_status()
                return RuleOutcome(**response.json())
        except Exception as e:
            print(f"DEBUG: Rule Check Failed: {e}")
            raise e


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


class StateManagerHTTPClient(StateManagerPort):
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
