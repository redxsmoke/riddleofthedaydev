import asyncio
import os
import asyncpg

async def recreate_table():
    db_url = os.getenv("DATABASE_URL")
    pool = await asyncpg.create_pool(dsn=db_url)
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS user_submitted_questions")
        await conn.execute("""
            CREATE TABLE user_submitted_questions (
                riddle_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    await pool.close()
