import os

from gm.db.database import db


async def init_db():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    conn = await db.get_pool().acquire()
    try:
        await conn.execute(schema_sql)
    finally:
        await db.get_pool().release(conn)
