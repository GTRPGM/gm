import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from fastapi import FastAPI, Request

from gm.api.v1.api import api_router
from gm.core.config import settings
from gm.infra.db.database import DatabaseHandler
from gm.infra.db.init_db import init_db


async def connect_and_init_db(db: DatabaseHandler) -> None:
    """Initialize database connection and schema."""
    try:
        await asyncio.wait_for(db.connect(), timeout=5.0)
        await init_db(db)
        print(f"Connected to database and initialized schema: {settings.POSTGRES_DB}")
    except Exception as e:
        print(f"Database connection failed: {e}. Server running without DB.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Initialize infrastructure
    db = DatabaseHandler(settings.database_dsn)

    # Load SQL queries
    import os

    queries_dir = os.path.join(os.path.dirname(__file__), "infra", "db", "queries")
    db.load_queries(queries_dir)

    app.state.db = db

    # Background initialization
    asyncio.create_task(connect_and_init_db(db))

    print("Server starting... Swagger UI: http://localhost:8020/docs")
    yield

    # Clean up
    await db.close()
    print("Database connection closed.")


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
async def health_check(request: Request) -> Dict[str, str]:
    db: DatabaseHandler = request.app.state.db
    try:
        await db.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}
