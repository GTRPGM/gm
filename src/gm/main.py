import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from fastapi import FastAPI

from gm.api.v1.api import api_router
from gm.core.config import settings
from gm.infra.db.database import db
from gm.infra.db.init_db import init_db


async def connect_and_init_db() -> None:
    """백그라운드에서 DB 연결 및 초기화를 시도합니다."""
    try:
        await asyncio.wait_for(db.connect(), timeout=3.0)

        if db._pool:
            await init_db()
            print("Database initialized successfully.")

    except asyncio.TimeoutError:
        print("Database connection timed out. Server running without DB.")
    except Exception as e:
        print(f"Database connection failed: {e}. Server running without DB.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    asyncio.create_task(connect_and_init_db())
    print("Server starting... Swagger UI: http://localhost:8020/docs")
    yield

    try:
        await db.disconnect()
    except Exception as e:
        print(f"Error disconnecting from database: {e}")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "GM Core Service is running"}


@app.get("/health")
async def health_check() -> Dict[str, str]:
    try:
        await db.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}
