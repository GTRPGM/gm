from contextlib import asynccontextmanager

from fastapi import FastAPI

from gm.api.v1.api import api_router
from gm.core.config import settings
from gm.db.database import db
from gm.db.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await db.connect()
        await init_db()
    except Exception as e:
        print(f"Failed to connect to database: {e}")

    yield

    # Shutdown
    await db.disconnect()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {"message": "GM Core Service is running"}


@app.get("/health")
async def health_check():
    try:
        await db.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}
