
import os
print(f"DEBUG: Loaded db.py from {os.path.abspath(__file__)}")

import asyncpg
import discord
 

db_pool = None  # Global pool variable

async def create_db_pool():
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
        print(f"[upsert_user] User {user_id} upserted with score={score}, streak={streak}")

async def get_user(user_id: int):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        print(f"[get_user] Fetched user {user_id}: {result}")
        return result

async def get_all_submitted_questions():
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM user_submitted_questions")
        print(f"[get_all_submitted_questions] Retrieved {len(rows)} questions")
        return rows

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
        print(f"[count_unused_questions_db] Counted {result} unused questions")
        return result or 0

async def get_all_streak_users():
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users WHERE streak > 0 OR score > 0")
        users = [str(row["user_id"]) for row in rows]
        print(f"[get_all_streak_users] Users with streak or score: {users}")
        return users

async def adjust_score_and_reset_streak(user_id: str, score_delta: int):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE users
            SET score = GREATEST(score + $1, 0),
                streak = 0
            WHERE user_id = $2
        """, score_delta, int(user_id))
        print(f"[adjust_score_and_reset_streak] Adjusted score by {score_delta} and reset streak for user {user_id}")

async def get_score(user_id: str) -> int:
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    print(f"[get_score] Called for user_id={user_id}")
    async with db_pool.acquire() as conn:
        score = await conn.fetchval("SELECT score FROM users WHERE user_id = $1", int(user_id))
        print(f"[get_score] Score for user {user_id}: {score}")
        return score if score is not None else 0

async def increment_score(user_id: str):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    print(f"[increment_score] Called for user_id={user_id}")
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, score, streak, created_at)
            VALUES ($1, 1, 0, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET score = users.score + 1
        """, int(user_id))
    print(f"[increment_score] Incremented score for user {user_id}")

async def increment_streak(user_id: str):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    print(f"[increment_streak] Called for user_id={user_id}")
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, score, streak, created_at)
            VALUES ($1, 0, 0, NOW())
            ON CONFLICT (user_id) DO NOTHING
        """, int(user_id))

        await conn.execute("""
            UPDATE users
            SET streak = streak + 1
            WHERE user_id = $1
        """, int(user_id))
    print(f"[increment_streak] Incremented streak for user {user_id}")
import asyncpg
import os

db_pool = None  # Global pool variable

async def create_db_pool():
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
        print(f"[upsert_user] User {user_id} upserted with score={score}, streak={streak}")

async def get_user(user_id: int):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        print(f"[get_user] Fetched user {user_id}: {result}")
        return result

async def get_all_submitted_questions():
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM user_submitted_questions")
        print(f"[get_all_submitted_questions] Retrieved {len(rows)} questions")
        return rows

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
        print(f"[count_unused_questions_db] Counted {result} unused questions")
        return result or 0

async def get_all_streak_users():
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users WHERE streak > 0 OR score > 0")
        users = [str(row["user_id"]) for row in rows]
        print(f"[get_all_streak_users] Users with streak or score: {users}")
        return users

async def adjust_score_and_reset_streak(user_id: str, score_delta: int):
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE users
            SET score = GREATEST(score + $1, 0),
                streak = 0
            WHERE user_id = $2
        """, score_delta, int(user_id))
        print(f"[adjust_score_and_reset_streak] Adjusted score by {score_delta} and reset streak for user {user_id}")

async def get_score(user_id: str) -> int:
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized. Call create_db_pool() first.")
    print(f"[get_score] Called for user_id={user_id}")
    async with db_pool.acquire() as conn:
        score = await conn.fetchval("SELECT score FROM users WHERE user_id = $1", int(user_id))
        print(f"[get_score] Score for user {user_id}: {score}")
        return score if score is not None else 0

import discord


async def update_user_score_and_streak(
async def update_user_score_and_streak(
    user_id: int,
    interaction: discord.Interaction,
    add_score: int = 0,
    add_streak: int = 0
):
    print("[update_user_score_and_streak] Start")

    if db_pool is None:
        print("[update_user_score_and_streak] ERROR: db_pool is None")
        raise RuntimeError("DB pool is not initialized.")

    print("[update_user_score_and_streak] Acquiring DB connection...")
    async with db_pool.acquire() as conn:
        print("[update_user_score_and_streak] Connection acquired")

        print("[update_user_score_and_streak] Fetching user row...")
        user = await conn.fetchrow("SELECT score, streak FROM users WHERE user_id = $1", user_id)
        print(f"[update_user_score_and_streak] Fetched user: {user}")

        if not user:
            print("[update_user_score_and_streak] User not found — sending embed")
            embed = discord.Embed(
                title="⛔ User Not Found",
                description=(
                    "That user does not yet exist in the database.\n\n"
                    "Have them **submit** or **answer** a riddle first — their account will be created automatically.\n"
                    "After that, this command will work."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            print("[update_user_score_and_streak] Sent error embed")
            return None, None

        new_score = max(user['score'] + add_score, 0)
        new_streak = max(user['streak'] + add_streak, 0)

        print(f"[update_user_score_and_streak] Updating user: score={new_score}, streak={new_streak}")
        await conn.execute(
            "UPDATE users SET score = $1, streak = $2 WHERE user_id = $3",
            new_score, new_streak, user_id
        )
        print("[update_user_score_and_streak] Update complete")

        return new_score, new_streak
