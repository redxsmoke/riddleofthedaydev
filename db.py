
import asyncpg
import os

db_pool = None

async def create_db_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=os.getenv("DATABASE_URL"))

async def upsert_user(user_id: int, score: int, streak: int):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, score, streak, created_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET score = EXCLUDED.score,
                streak = EXCLUDED.streak
        """, user_id, score, streak)

async def get_user(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

async def insert_submitted_question(user_id: int, question: str, answer: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_submitted_questions (user_id, question, answer, created_at)
            VALUES ($1, $2, $3, NOW())
        """, user_id, question, answer)

async def get_all_submitted_questions():
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM user_submitted_questions")

async def insert_submitted_question(user_id: int, question: str, answer: str):
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_submitted_questions (user_id, question, answer, created_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                """,
                user_id, question, answer
            )
        print(f"[insert_submitted_question] Inserted riddle by user {user_id}")
    except Exception as e:
        print(f"[insert_submitted_question] ERROR inserting riddle: {e}")
