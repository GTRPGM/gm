from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from gm.main import app


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def mock_database(monkeypatch):
    """
    실제 DB 연결을 차단하고 Mock으로 대체합니다.
    """
    # 1. Mock 메서드 생성
    mock_connect = AsyncMock()
    mock_disconnect = AsyncMock()

    # _get_next_turn_seq에서 호출 시 1을 반환 (첫 번째 턴)
    # health check의 'SELECT 1'도 1을 반환하므로 호환됨
    mock_fetchval = AsyncMock(return_value=1)

    mock_execute = AsyncMock()
    mock_fetch = AsyncMock(return_value=[])
    mock_fetchrow = AsyncMock(return_value=None)

    # 2. gm.db.database.Database 클래스의 메서드들을 교체
    # gm.db.database.db는 Database 클래스 자체를 가리킴
    monkeypatch.setattr("gm.db.database.Database.connect", mock_connect)
    monkeypatch.setattr("gm.db.database.Database.disconnect", mock_disconnect)
    monkeypatch.setattr("gm.db.database.Database.fetchval", mock_fetchval)
    monkeypatch.setattr("gm.db.database.Database.execute", mock_execute)
    monkeypatch.setattr("gm.db.database.Database.fetch", mock_fetch)
    monkeypatch.setattr("gm.db.database.Database.fetchrow", mock_fetchrow)


@pytest_asyncio.fixture(scope="function")
async def client():
    # lifespan 관리는 httpx.AsyncClient가 app을 실행할 때 처리됨
    # Mock핑 되었으므로 실제 DB 연결은 발생하지 않음
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
