import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from gm.db.database import db
from gm.db.init_db import init_db
from gm.main import app


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="function")
async def client():
    # 명시적으로 DB 연결 및 초기화

    await db.connect()

    await init_db()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    await db.disconnect()
