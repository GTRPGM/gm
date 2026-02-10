import pytest
from gm.infra.db.database import DatabaseHandler
from gm.main import app, connect_and_init_db

@pytest.mark.asyncio
async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "GM Core Service is running"}


@pytest.mark.asyncio
async def test_health_check_success(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_health_check_failure(client, mocker):
    mock_db = mocker.AsyncMock(spec=DatabaseHandler)
    mock_db.fetchval.side_effect = Exception("DB error")

    mocker.patch.object(app.state, "db", mock_db)

    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "DB error" in response.json()["db"]


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
async def test_connect_and_init_db_success(mocker):
    mock_db = mocker.AsyncMock(spec=DatabaseHandler)
    mock_init = mocker.patch("gm.main.init_db", new_callable=mocker.AsyncMock)

    await connect_and_init_db(mock_db)

    mock_db.connect.assert_called_once()
    mock_init.assert_called_once_with(mock_db)


@pytest.mark.asyncio
async def test_connect_and_init_db_failure(mocker):
    mock_db = mocker.AsyncMock(spec=DatabaseHandler)
    mock_db.connect.side_effect = Exception("Conn failed")

    with pytest.raises(Exception, match="Conn failed"):
        await connect_and_init_db(mock_db)

    assert mock_db.connect.call_count > 1


@pytest.mark.asyncio
async def test_reconnect_database_success(client, mocker):
    mock_db = mocker.AsyncMock()
    mock_init = mocker.patch(
        "gm.api.v1.endpoints.system.init_db", new_callable=mocker.AsyncMock
    )

    old_db = app.state.db
    app.state.db = mock_db

    try:
        response = await client.post("/api/v1/system/reconnect")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        mock_db.close.assert_called_once()
        mock_db.connect.assert_called_once()
        mock_init.assert_called_once_with(mock_db)
    finally:
        app.state.db = old_db


@pytest.mark.asyncio
async def test_reconnect_database_failure(client, mocker):
    mock_db = mocker.AsyncMock()
    mock_db.connect.side_effect = Exception("Hard failure")

    old_db = app.state.db
    app.state.db = mock_db

    try:
        response = await client.post("/api/v1/system/reconnect")
        assert response.status_code == 503
        assert "Hard failure" in response.json()["detail"]["message"]
    finally:
        app.state.db = old_db
