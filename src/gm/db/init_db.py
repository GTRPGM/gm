import os

from gm.db.database import db


async def init_db():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    # 세미콜론으로 구분된 쿼리들을 실행하거나, asyncpg의 execute가 다중 쿼리를 지원하는지 확인 필요.
    # asyncpg execute는 단일 문장만 지원할 수 있으므로, script 메서드를 사용하거나 분리해야 함.
    # 하지만 asyncpg는 .execute()로 다중 명령을 지원하지 않을 수 있음.
    # 보통은 connection.execute()로 DDL 여러개를 한 번에 실행하는 건 드라이버/설정에 따라 다름.
    # 안전하게 나눠서 실행하거나 script 같은 기능 확인.

    # asyncpg connection has .execute() which runs a command.
    # For multiple statements, use connection.execute() block or split manually?
    # asyncpg documentation says execute() executes a SQL statement.
    # Let's try to execute the whole block. If it fails, we split.
    # Actually, asyncpg allows multiple statements in execute() if they are simple DDLs usually?
    # No, it's safer to read and execute.

    # 간단히 스크립트 파일 내용을 읽어서 실행.
    # asyncpg connection object has a generic execute method.

    conn = await db.get_pool().acquire()
    try:
        await conn.execute(schema_sql)
    finally:
        await db.get_pool().release(conn)
