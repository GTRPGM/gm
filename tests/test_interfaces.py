import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from gm.core.config import settings
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)
from gm.plugins.external.http_client import (
    ScenarioManagerHTTPClient,
    StateManagerHTTPClient,
)
from gm.schemas.common import EntityDiff
from gm.schemas.scenario import ScenarioConstraintType, ScenarioSuggestion


class MockRuleManager(RuleManagerPort):
    async def get_proposal(self, context: Dict[str, Any]):
        return None

    async def check_health(self) -> bool:
        return True


class MockScenarioManager(ScenarioManagerPort):
    async def get_proposal(self, context: Dict[str, Any]):
        return None

    async def check_health(self) -> bool:
        return True


class MockStateManager(StateManagerPort):
    async def commit(self, session_id: str, diffs: List[EntityDiff], output_type: str):
        return {}

    async def get_state(self, session_id: str):
        return {}

    async def get_act_details(self, session_id: str):
        return {}

    async def get_sequence_details(self, session_id: str):
        return {}

    async def update_act(self, session_id: str, act_id: str, seq_id: str):
        return {}

    async def update_sequence(self, session_id: str, seq_id: str):
        return {}

    async def end_session(self, session_id: str):
        return {}

    async def check_health(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_interfaces_instantiation():
    rule_mgr = MockRuleManager()
    assert await rule_mgr.check_health() is True

    scen_mgr = MockScenarioManager()
    assert await scen_mgr.check_health() is True

    state_mgr = MockStateManager()
    assert await state_mgr.check_health() is True


def test_abstract_instantiation_error():
    with pytest.raises(TypeError):
        RuleManagerPort()
    with pytest.raises(TypeError):
        ScenarioManagerPort()
    with pytest.raises(TypeError):
        StateManagerPort()


@pytest.mark.asyncio
async def test_state_update_act_payload_matches_state_contract(respx_mock):
    client = StateManagerHTTPClient()
    route = respx_mock.put(f"{settings.STATE_MANAGER_URL}/state/session/s1/act").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {}})
    )

    await client.update_act("s1", "act-2", "seq-2-1")

    payload = json.loads(route.calls[0].request.content)
    assert payload["new_act_id"] == "act-2"
    assert payload["new_sequence_id"] == "seq-2-1"