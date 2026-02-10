import httpx
import pytest
from gm.core.config import settings
from gm.plugins.external.http_client import StateManagerHTTPClient
from gm.schemas.common import EntityDiff

@pytest.mark.asyncio
async def test_state_manager_get_state(respx_mock):
    # 전역 Mock 제거
    respx_mock.routes.clear()
    
    client = StateManagerHTTPClient()
    respx_mock.get(f"{settings.STATE_MANAGER_URL}/state/session/unique_s1").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {"session_id": "unique_s1"}})
    )

    state = await client.get_state("unique_s1")
    assert state["session_id"] == "unique_s1"


@pytest.mark.asyncio
async def test_state_manager_commit(respx_mock):
    respx_mock.routes.clear()
    
    client = StateManagerHTTPClient()
    respx_mock.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {"commit_id": "c1"}})
    )

    diffs = [EntityDiff(entity_id="p1", diff={"hp": -10})]
    result = await client.commit("s1:1", diffs)
    assert result["commit_id"] == "c1"


@pytest.mark.asyncio
async def test_relation_output_mapping(respx_mock):
    respx_mock.routes.clear()
    
    client = StateManagerHTTPClient()
    respx_mock.get(f"{settings.STATE_MANAGER_URL}/state/session/rel_unique").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "rel_unique",
                    "world_snapshot": {
                        "entity_relations": [
                            {"from_id": "A", "to_id": "B", "relation_type": "FRIENDLY", "affinity": 50}
                        ]
                    }
                }
            }
        )
    )

    state = await client.get_state("rel_unique")
    relations = state["world_snapshot"].get("entity_relations", [])
    assert len(relations) == 1
    assert relations[0]["from_id"] == "A"
