import httpx
import pytest
from gm.core.config import settings
from gm.plugins.external.http_client import ScenarioManagerHTTPClient
from gm.schemas.rule_engine import RuleOutcome

@pytest.mark.asyncio
async def test_scenario_manager_client_health(respx_mock):
    client = ScenarioManagerHTTPClient()
    respx_mock.get(f"{settings.SCENARIO_SERVICE_URL}/health").mock(
        return_value=httpx.Response(200, json={"status": "UP"})
    )
    assert await client.check_health() is True


@pytest.mark.asyncio
async def test_scenario_manager_get_proposal(respx_mock):
    client = ScenarioManagerHTTPClient()
    respx_mock.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate").mock(
        return_value=httpx.Response(200, json={
            "status": "success",
            "data": {
                "is_triggered": True,
                "reason": "Stop",
                "should_end": True
            }
        })
    )

    context = {
        "rule_outcome": RuleOutcome(session_id="s1", scenario_id="scn1", success=True, reason="ok", suggested={"diffs": [], "relations": []}),
        "world_snapshot": {"current_act_id": "act-1", "current_sequence_id": "seq-1"}
    }
    result = await client.get_proposal(context)
    assert result.should_end is True
    assert result.constraint_type.value.lower() == "mandatory"