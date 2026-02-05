from unittest.mock import AsyncMock

import pytest

from gm.main import app


@pytest.mark.asyncio
async def test_reconnect_database_success(client, mocker):
    mock_db = mocker.AsyncMock()
    mock_init = mocker.patch(
        "gm.api.v1.endpoints.system.init_db", new_callable=AsyncMock
    )

    # app.state.db를 Mock으로 교체
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
