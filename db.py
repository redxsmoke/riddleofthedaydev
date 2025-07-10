import asyncpg
import os

db_pool = None  # Global pool variable

async def create_db_pool():
    """Create and set the global asyncpg pool from DATABASE_URL env var."""
    global db_pool
    if db_pool is None:
        print("⏳ Creating database connection pool...")
        db_pool = await asyncpg.create_pool(dsn=os.getenv("DATABASE_URL"))
        print("✅ Database connection pool created.")
    else:
        print("⚠️ Database pool already initialized.")
    return db_pool

def get_db_pool():
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    return db_pool


async def upsert_user(user_id: int, score: int, streak: int):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, score, streak, created_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET score = EXCLUDED.score,
                streak = EXCLUDED.streak
        """, user_id, score, streak)

async def get_user(user_id: int):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

async def get_all_submitted_questions():
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM user_submitted_questions")

async def insert_submitted_question(user_id: int, question: str, answer: str):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_submitted_questions (user_id, question, answer, created_at)
                VALUES ($1, $2, $3, NOW())
                """,
                user_id, question, answer
            )
        print(f"[insert_submitted_question] Inserted riddle by user {user_id}")
    except Exception as e:
        print(f"[insert_submitted_question] ERROR inserting riddle: {e}")

async def count_unused_questions_db():
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        result = await conn.fetchval("SELECT COUNT(*) FROM user_submitted_questions WHERE posted_at IS NULL")
    return result or 0
