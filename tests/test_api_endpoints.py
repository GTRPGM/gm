import pytest

from gm.exceptions import PipelineError
from gm.main import app


@pytest.mark.asyncio
async def test_process_turn_pipeline_error(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.AsyncMock()
    mock_engine.process_player_turn.side_effect = PipelineError(
        node_name="test_node", message="Test Pipeline Error", service_name="TestService"
    )

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    payload = {"session_id": "test_session", "content": "action"}
    response = await client.post("/api/v1/game/turn", json=payload)

    assert response.status_code == 502
    assert response.json()["detail"]["failed_node"] == "test_node"


@pytest.mark.asyncio
async def test_process_turn_unexpected_error(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.AsyncMock()
    mock_engine.process_player_turn.side_effect = Exception("Unexpected")

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    payload = {"session_id": "test_session", "content": "action"}
    response = await client.post("/api/v1/game/turn", json=payload)

    assert response.status_code == 500
    assert response.json()["detail"]["error_type"] == "UnexpectedError"


@pytest.mark.asyncio
async def test_get_history_success(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.AsyncMock()
    mock_engine.get_session_history.return_value = [
        {
            "session_id": "session_123",
            "act_id": "act-1",
            "sequence_id": "seq-1",
            "sequence_type": "EXPLORATION",
            "sequence_seq": 1,
            "turn_seq": 1,
            "active_entity_id": "player",
            "user_input": "test input",
            "narrative": "test",
            "created_at": "2026-02-07T00:00:00+00:00",
        }
    ]

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    response = await client.get("/api/v1/game/history/session_123")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["turn_seq"] == 1
    assert response.json()[0]["narrative"] == "test"


@pytest.mark.asyncio
async def test_get_history_error(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.AsyncMock()
    mock_engine.get_session_history.side_effect = Exception("DB Error")

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    response = await client.get("/api/v1/game/history/session_123")

    assert response.status_code == 500
    assert "DB Error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_process_npc_turn_pipeline_error(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.AsyncMock()
    mock_engine.process_npc_turn.side_effect = PipelineError(
        node_name="npc_node", message="NPC Error"
    )

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    payload = {"session_id": "test_session"}
    response = await client.post("/api/v1/game/npc-turn", json=payload)

    assert response.status_code == 502
    assert response.json()["detail"]["failed_node"] == "npc_node"


@pytest.mark.asyncio
async def test_process_npc_turn_unexpected_error(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.AsyncMock()
    mock_engine.process_npc_turn.side_effect = Exception("Unexpected NPC Error")

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    payload = {"session_id": "test_session"}
    response = await client.post("/api/v1/game/npc-turn", json=payload)

    assert response.status_code == 500
    assert response.json()["detail"]["error_type"] == "UnexpectedError"


@pytest.mark.asyncio
async def test_system_status_degraded(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.Mock()

    mock_engine.rule_client.check_health = mocker.AsyncMock(return_value=True)
    mock_engine.scenario_client.check_health = mocker.AsyncMock(return_value=False)
    mock_engine.state_client.check_health = mocker.AsyncMock(return_value=True)
    mock_engine.llm.check_health = mocker.AsyncMock(return_value=True)

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    response = await client.get("/api/v1/system/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["services"]["scenario_manager"] == "error"


@pytest.mark.asyncio
async def test_system_status_exception(client, mocker):
    from gm.core.deps import get_game_engine

    mock_engine = mocker.Mock()

    mock_engine.rule_client.check_health = mocker.AsyncMock(
        side_effect=Exception("Connection reset")
    )
    mock_engine.scenario_client.check_health = mocker.AsyncMock(return_value=True)
    mock_engine.state_client.check_health = mocker.AsyncMock(return_value=True)
    mock_engine.llm.check_health = mocker.AsyncMock(return_value=True)

    mocker.patch.dict(app.dependency_overrides, {get_game_engine: lambda: mock_engine})
    response = await client.get("/api/v1/system/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert "error: Connection reset" in data["services"]["rule_manager"]
