pip install asyncpg

import asyncpg
import os

db_pool = None

async def load_all_user_scores():
    global scores, streaks
    scores = {}
    streaks = {}
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, score, streak FROM users")
        for row in rows:
            uid = str(row["user_id"])
            scores[uid] = row["score"]
            streaks[uid] = row["streak"]


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

# Add more functions as needed...
