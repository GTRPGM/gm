import os
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

import asyncpg


class DatabaseHandler:
    """Infrastructure: Low-level asyncpg connection pool handler with query loading."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None
        self._queries: Dict[str, str] = {}

    async def connect(self) -> None:
        """Initialize the connection pool."""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Provides a connection from the pool as a context manager."""
        if self.pool is None:
            await self.connect()
        async with self.pool.acquire() as conn:
            yield conn

    def load_queries(self, queries_dir: str) -> None:
        """Load SQL queries from the specified directory."""
        if not os.path.exists(queries_dir):
            return

        for filename in os.listdir(queries_dir):
            if filename.endswith(".sql"):
                with open(os.path.join(queries_dir, filename), "r") as f:
                    content = f.read()
                    self._parse_queries(content)

    def _parse_queries(self, content: str) -> None:
        """Parse SQL file content into a dictionary of named queries."""
        pattern = re.compile(r"--\s*name:\s*(\w+)\s*(.*?)(?=--\s*name:|$)", re.DOTALL)
        matches = pattern.findall(content)
        for name, sql in matches:
            self._queries[name] = sql.strip()

    def get_query(self, name: str) -> str:
        """Retrieve a loaded query by name."""
        if name not in self._queries:
            raise KeyError(f"Query '{name}' not found. Ensure it's loaded.")
        return self._queries[name]

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query without returning results."""
        async with self.get_connection() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> List[asyncpg.Record]:
        """Execute a query and fetch all results."""
        async with self.get_connection() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        """Execute a query and fetch a single row."""
        async with self.get_connection() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Execute a query and fetch a single value."""
        async with self.get_connection() as conn:
            return await conn.fetchval(query, *args)

    async def close(self) -> None:
        """Gracefully close the connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
