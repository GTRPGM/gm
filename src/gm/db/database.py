from typing import Optional

import asyncpg

from gm.core.config import settings


class Database:
    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def connect(cls):
        if cls._pool is None:
            cls._pool = await asyncpg.create_pool(
                dsn=settings.database_dsn, min_size=1, max_size=10, command_timeout=60
            )
            print(f"Connected to database: {settings.POSTGRES_DB}")

    @classmethod
    async def disconnect(cls):
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            print("Disconnected from database")

    @classmethod
    def get_pool(cls) -> asyncpg.Pool:
        if cls._pool is None:
            raise RuntimeError("Database is not initialized. Call connect() first.")
        return cls._pool

    @classmethod
    async def execute(cls, query: str, *args):
        pool = cls.get_pool()
        async with pool.acquire() as connection:
            return await connection.execute(query, *args)

    @classmethod
    async def fetch(cls, query: str, *args):
        pool = cls.get_pool()
        async with pool.acquire() as connection:
            return await connection.fetch(query, *args)

    @classmethod
    async def fetchrow(cls, query: str, *args):
        pool = cls.get_pool()
        async with pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    @classmethod
    async def fetchval(cls, query: str, *args):
        pool = cls.get_pool()
        async with pool.acquire() as connection:
            return await connection.fetchval(query, *args)


db = Database
