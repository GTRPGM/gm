import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response

from gm.core.config import settings
from gm.core.deps import get_db
from gm.infra.db.database import DatabaseHandler
from gm.main import app


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def test_queries_dir():
    """실제 프로젝트의 쿼리 디렉토리 경로"""
    return os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "src",
        "gm",
        "infra",
        "db",
        "queries",
    )


@pytest.fixture
def mock_db_handler(test_queries_dir):
    """
    실제 DB 핸들러를 Mock으로 대체합니다.
    쿼리 로딩 기능은 유지하되, 네트워크 호출만 Mocking합니다.
    """
    handler = DatabaseHandler("postgresql://mock:mock@localhost/mock")
    # 실제 쿼리들을 로드하여 get_query()가 작동하게 함
    handler.load_queries(test_queries_dir)

    # 메서드들을 AsyncMock으로 대체
    handler.connect = AsyncMock()
    handler.close = AsyncMock()
    handler.execute = AsyncMock(return_value="INSERT 0 1")
    handler.fetch = AsyncMock(return_value=[])
    handler.fetchval = AsyncMock(return_value=1)
    handler.fetchrow = AsyncMock(return_value=None)

    return handler


@pytest.fixture(autouse=True)
def override_dependencies(mock_db_handler):
    """
    FastAPI 의존성 주입을 Mock DB 핸들러로 덮어씁니다.
    """
    app.dependency_overrides[get_db] = lambda: mock_db_handler
    # app.state.db도 설정 (lifespan을 건너뛰는 테스트를 위해)
    app.state.db = mock_db_handler
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_external_services(respx_mock):
    """
    외부 서비스 호출을 가로챕니다.
    실제 Pydantic 스키마를 완벽히 준수하도록 Mock 응답을 구성합니다.
    """
    # Rule Manager: RuleOutcomeData 스키마 준수
    respx_mock.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "test_session",
                    "scenario_id": "scen-1",
                    "phase_type": "EXPLORATION",
                    "reason": "Mock Rule Check Success",
                    "success": True,
                    "suggested": {
                        "diffs": [{"state_entity_id": "dummy", "diff": {"hp": 90}}],
                        "relations": [],
                    },
                    "value_range": None,
                    "logs": [],
                },
                "message": "OK",
            },
        )
    )

    # Scenario Manager: ScenarioSuggestion 스키마 준수
    respx_mock.post(f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "constraint_type": "advisory",
                    "description": "Mock scenario check",
                    "correction_diffs": [],
                    "next_act_id": None,
                    "next_seq_id": None,
                    "should_end": False,
                    "narrative_slot": None,
                },
            },
        )
    )

    # State Manager Commit
    respx_mock.post(f"{settings.STATE_MANAGER_URL}/state/commit").mock(
        return_value=Response(
            200, json={"commit_id": "mock_commit_12345", "status": "success"}
        )
    )

    # State Manager Get State
    respx_mock.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/[^/]+$"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "test_session",
                    "status": "active",
                    "current_act_id": "act-1",
                    "current_sequence_id": "seq-1",
                    "world_snapshot": {
                        "player_id": "player_1",
                        "npcs": [],
                        "enemies": [],
                    },
                },
            },
        )
    )

    # State Manager Get Sequence Details
    respx_mock.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*/sequence/details"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "npcs": [],
                    "enemies": [],
                    "sequence_id": "seq-1",
                    "goal": "상황에 몰입하기",
                    "exit_triggers": [],
                },
            },
        )
    )

    # State Manager Get Act Details
    respx_mock.get(
        url__regex=f"{settings.STATE_MANAGER_URL}/state/session/.*/act/details"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "data": {
                    "act_id": "act-1",
                    "act_name": "제 1막",
                    "sequence_ids": ["seq-1", "seq-2"],
                },
            },
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
                            "content": "Mock Narrative Result: Success",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )
    )

    return respx_mock


@pytest_asyncio.fixture(scope="function")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c