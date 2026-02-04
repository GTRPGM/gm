import pytest

from gm.infra.db.database import DatabaseHandler
from gm.main import app, connect_and_init_db


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

    # Should reraise exception after retries
    with pytest.raises(Exception, match="Conn failed"):
        await connect_and_init_db(mock_db)

    # Verify connect was called multiple times due to retry
    assert mock_db.connect.call_count > 1


@pytest.mark.asyncio
async def test_health_check_failure(client, mocker):
    mock_db = mocker.AsyncMock(spec=DatabaseHandler)
    mock_db.fetchval.side_effect = Exception("DB error")

    mocker.patch.object(app.state, "db", mock_db)

    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "DB error" in response.json()["db"]
