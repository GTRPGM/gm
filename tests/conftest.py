from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response

from gm.core.config import settings
from gm.main import app


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def mock_database(monkeypatch):
    """
    실제 DB 연결을 차단하고 Mock으로 대체합니다.
    """
    mock_connect = AsyncMock()
    mock_disconnect = AsyncMock()
    mock_fetchval = AsyncMock(return_value=1)
    mock_execute = AsyncMock()
    mock_fetch = AsyncMock(return_value=[])
    mock_fetchrow = AsyncMock(return_value=None)

    monkeypatch.setattr("gm.infra.db.database.Database.connect", mock_connect)
    monkeypatch.setattr("gm.infra.db.database.Database.disconnect", mock_disconnect)
    monkeypatch.setattr("gm.infra.db.database.Database.fetchval", mock_fetchval)
    monkeypatch.setattr("gm.infra.db.database.Database.execute", mock_execute)
    monkeypatch.setattr("gm.infra.db.database.Database.fetch", mock_fetch)
    monkeypatch.setattr("gm.infra.db.database.Database.fetchrow", mock_fetchrow)


@pytest.fixture(autouse=True)
def mock_external_services(respx_mock):
    """
    respx_mock fixture를 사용하여 외부 서비스 호출을 가로챕니다.
    """
    # Rule Manager
    respx_mock.post(f"{settings.RULE_SERVICE_URL}/api/v1/rule/check").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "test_session",
                    "scenario_id": 1,
                    "phase_type": "탐험",
                    "reason": "Mock Rule Check",
                    "success": True,
                    "suggested": {
                        "diffs": [{"entity_id": "dummy", "diff": {"hp": 90}}],
                        "relations": [],
                    },
                    "value_range": None,
                },
                "message": "OK",
            },
        )
    )

    # Scenario Manager
    respx_mock.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/scenario/check").mock(
        return_value=Response(
            200,
            json={
                "constraint_type": "advisory",
                "description": "Mock Scenario Check",
                "correction_diffs": [],
                "narrative_slot": None,
            },
        )
    )

    # State Manager
    respx_mock.post(f"{settings.STATE_SERVICE_URL}/api/v1/state/commit").mock(
        return_value=Response(
            200, json={"commit_id": "mock_commit_12345", "status": "success"}
        )
    )

    # LLM Gateway: Narrative
    respx_mock.post(f"{settings.LLM_GATEWAY_URL}/api/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1234567890,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Mock Narrative Result",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )
    )

    # LLM Gateway: NPC Action
    respx_mock.post(f"{settings.LLM_GATEWAY_URL}/api/v1/llm/npc-action").mock(
        return_value=Response(200, json={"action_text": "NPC Mock Action"})
    )

    return respx_mock


@pytest_asyncio.fixture(scope="function")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
