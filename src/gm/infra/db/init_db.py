import os

from gm.infra.db.database import DatabaseHandler


async def init_db(db: DatabaseHandler) -> None:
    """Initialize the database schema."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    await db.execute(schema_sql)
