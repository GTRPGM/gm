import pytest
from gm.exceptions import PipelineError
from gm.main import app


@pytest.mark.asyncio
async def test_process_turn_success(client):
    payload = {"session_id": "test_session_1", "content": "나는 문을 발로 찬다."}
    response = await client.post("/api/v1/game/turn", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "turn_id" in data
    assert "narrative" in data
    assert "commit_id" in data
    assert data["output_type"] == "narration"
    assert data["active_entity_name"] == "player"
    assert data["turn_id"].startswith("test_session_1:")


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
async def test_process_npc_turn_success(client):
    session_id = "npc_test_session"
    payload = {"session_id": session_id}
    response = await client.post("/api/v1/game/npc-turn", json=payload)

    assert response.status_code == 200
    result = response.json()

    assert "turn_id" in result
    assert "narrative" in result
    assert "commit_id" in result
    assert result["output_type"] in ("npc", "narration")
    assert result["turn_id"].startswith(f"{session_id}:")


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
async def test_rule_manager_api_integration(client, respx_mock):
    from gm.core.config import settings

    session_id = "rule_test_session"

    mock_response = {
        "status": "success",
        "data": {
            "session_id": "1",
            "scenario_id": "101",
            "phase_type": "COMBAT",
            "reason": "Success",
            "success": True,
            "suggested": {"diffs": [], "relations": []},
        },
    }

    respx_mock.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=pytest.importorskip("httpx").Response(200, json=mock_response)
    )
    payload = {"session_id": session_id, "content": "Attack"}

    response = await client.post("/api/v1/game/turn", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "narrative" in data
