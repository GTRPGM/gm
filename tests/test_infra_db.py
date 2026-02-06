import asyncpg
import pytest

from gm.infra.db.database import DatabaseHandler


@pytest.fixture
def db_handler():
    dsn = "postgresql://user:password@localhost:5432/db"
    return DatabaseHandler(dsn)


def test_parse_queries(db_handler):
    content = """
-- name: get_user
SELECT * FROM users WHERE id = $1;
-- name: list_users
SELECT * FROM users;
"""
    db_handler._parse_queries(content)
    assert db_handler.get_query("get_user") == "SELECT * FROM users WHERE id = $1;"
    assert db_handler.get_query("list_users") == "SELECT * FROM users;"


def test_get_query_not_found(db_handler):
    with pytest.raises(KeyError):
        db_handler.get_query("missing_query")


def test_load_queries_missing_dir(db_handler, mocker):
    mocker.patch("os.path.exists", return_value=False)
    db_handler.load_queries("/non/existent/dir")
    assert db_handler._queries == {}


@pytest.mark.asyncio
async def test_connect_already_connected(db_handler, mocker):
    mock_pool = mocker.Mock(spec=asyncpg.Pool)
    db_handler.pool = mock_pool
    mock_create = mocker.patch("asyncpg.create_pool")
    await db_handler.connect()
    assert mock_create.call_count == 0


@pytest.mark.asyncio
async def test_close_no_pool(db_handler):
    await db_handler.close()
    assert db_handler.pool is None


@pytest.mark.asyncio
async def test_database_operations(mocker):
    dsn = "postgresql://user:password@localhost:5432/db"
    handler = DatabaseHandler(dsn)

    mock_conn = mocker.AsyncMock(spec=asyncpg.Connection)
    mock_pool = mocker.Mock(spec=asyncpg.Pool)
    # Async context manager mocking
    mock_pool.acquire.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = mocker.AsyncMock()

    handler.pool = mock_pool

    await handler.execute("INSERT INTO test VALUES (1)")
    mock_conn.execute.assert_called_once_with("INSERT INTO test VALUES (1)")

    await handler.fetch("SELECT * FROM test")
    mock_conn.fetch.assert_called_once_with("SELECT * FROM test")

    await handler.fetchrow("SELECT * FROM test LIMIT 1")
    mock_conn.fetchrow.assert_called_once_with("SELECT * FROM test LIMIT 1")

    await handler.fetchval("SELECT count(*) FROM test")
    mock_conn.fetchval.assert_called_once_with("SELECT count(*) FROM test")

    await handler.close()
    mock_pool.close.assert_called_once()
    assert handler.pool is None


@pytest.mark.asyncio
async def test_init_db(mocker):
    from gm.infra.db.init_db import init_db

    mock_db = mocker.AsyncMock(spec=DatabaseHandler)

    mocker.patch("builtins.open", mocker.mock_open(read_data="CREATE TABLE test;"))
    await init_db(mock_db)

    mock_db.execute.assert_called_once_with("CREATE TABLE test;")
