import os
import re
import random
import traceback
import asyncio
from datetime import datetime, timezone, time, timedelta

import discord
from discord import app_commands, Interaction, Embed
from discord.ext import tasks
from discord.ui import View, Button

import asyncpg

import db
import commands
from views import LeaderboardView, create_leaderboard_embed
from db import create_db_pool, upsert_user, get_user, insert_submitted_question, get_all_submitted_questions


intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# REMOVED local db_pool = None — use db.db_pool everywhere

current_riddle = None
current_answer_revealed = False
correct_users = set()
guess_attempts = {}
deducted_for_user = set()

STOP_WORDS = {"a", "an", "the", "is", "was", "were", "of", "to", "and", "in", "on", "at", "by"}

def clean_and_filter(text):
    words = re.findall(r'\b\w+\b', text.lower())
    return [w for w in words if w not in STOP_WORDS]
    

async def count_unused_questions():
    async with db.db_pool.acquire() as conn:
        result = await conn.fetchval("SELECT COUNT(*) FROM user_submitted_questions WHERE posted_at IS NULL")
    return result or 0


async def get_unused_questions():
    async with db.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT riddle_id, question, answer, user_id FROM user_submitted_questions WHERE posted_at IS NULL"
        )
        return [dict(row) for row in rows]


async def format_question_embed(qdict, submitter=None):
    embed = discord.Embed(
        title=f"🧠 Riddle #{qdict['riddle_id']}",
        description=qdict['question'],
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Answer will be revealed at 23:00 UTC. Use /submitriddle to contribute your own!")

    remaining = await count_unused_questions()
    if remaining < 5:
        embed.add_field(
            name="⚠️ Riddle Supply Low",
            value="Less than 5 new riddles remain - submit one with `/submitriddle`!",
            inline=False
        )
    if submitter:
        embed.add_field(
            name="Submitted By",
            value=submitter.mention,
            inline=False
        )
    return embed


def get_rank(score, streak=0):
    # Example rank calculation, customize as needed
    if score > 0:
        if streak >= 30:
            return "💚🔥 Wasabi Warlord (30+ day streak)"
        elif streak >= 20:
            return "🥢 Rollmaster Ronin (20+ day streak)"
        elif streak >= 10:
            return "🍣 Nigiri Ninja (10+ day streak)"
        elif streak >= 5:
            return "🍤 Tempura Titan (5+ day streak)"
        elif streak >= 3:
            return "🔥 Streak Samurai (3+ day streak)"
        if score <= 5:
            return "Sushi Newbie 🍽️"
        elif 6 <= score <= 15:
            return "Maki Novice 🍣"
        elif 16 <= score <= 25:
            return "Sashimi Skilled 🍤"
        elif 26 <= score <= 50:
            return "Brainy Botan 🧠"
        else:
            return "Sushi Einstein 🧪"
    else:
        return "Sushi Newbie 🍽️"


@client.event
async def on_message(message):
    if message.author.bot:
        return

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    if message.channel.id != ch_id:
        return

    global correct_users, guess_attempts, deducted_for_user, current_riddle, current_answer_revealed

    user_id = str(message.author.id)
    content = message.content.strip()

    if not current_riddle or current_answer_revealed:
        return

    if current_riddle.get("user_id") == user_id:
        user_words = clean_and_filter(content)
        answer_words = clean_and_filter(current_riddle["answer"])

        if any(word in answer_words for word in user_words):
            try:
                await message.delete()
            except:
                pass
            await message.channel.send(
                "⛔ You submitted this riddle and cannot answer it.",
                delete_after=10
            )
            return
        else:
            return

    if user_id in correct_users:
        try: await message.delete()
        except: pass
        await message.channel.send(
            f"✅ You already answered correctly, {message.author.mention}. No more guesses counted.",
            delete_after=5
        )
        return

    attempts = guess_attempts.get(user_id, 0)
    if attempts >= 5:
        try: await message.delete()
        except: pass
        await message.channel.send(
            f"❌ You are out of guesses for this riddle, {message.author.mention}.",
            delete_after=5
        )
        return

    guess_attempts[user_id] = attempts + 1

    user_words = clean_and_filter(content)
    answer_words = clean_and_filter(current_riddle["answer"])

    if any(word in user_words for word in answer_words):
        correct_users.add(user_id)
        await db.increment_score(user_id)
        await db.increment_streak(user_id)

        new_score = await db.get_score(user_id)

        try:
            await message.delete()
        except:
            pass

        correct_guess_embed = discord.Embed(
            title="You guess correctly!",
            description=f"🥳 Correct, {message.author.mention}! Your total score: {new_score}",
            color=discord.Color.green()
        )
        await message.channel.send(embed=correct_guess_embed)
    else:
        remaining = 5 - guess_attempts.get(user_id, 0)
        if remaining == 0 and user_id not in deducted_for_user:
            await db.decrement_score(user_id)
            await db.reset_streak(user_id)
            deducted_for_user.add(user_id)
            await message.channel.send(
                f"❌ Incorrect, {message.author.mention}. You've used all guesses and lost 1 point.",
                delete_after=8
            )
        elif remaining > 0:
            await message.channel.send(
                f"❌ Incorrect, {message.author.mention}. {remaining} guess(es) left.",
                delete_after=6
            )
        try:
            await message.delete()
        except:
            pass

    now_utc = datetime.now(timezone.utc)
    reveal_dt = datetime.combine(now_utc.date(), time(23, 0), tzinfo=timezone.utc)
    if now_utc >= reveal_dt:
        reveal_dt += timedelta(days=1)
    delta = reveal_dt - now_utc
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    countdown_msg = (
        f"⏳ Answer will be revealed in {hours} hour{'s' if hours != 1 else ''} "
        f"{minutes} minute{'s' if minutes != 1 else ''}."
    )
    await message.channel.send(countdown_msg, delete_after=12)
@client.event
async def on_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.errors.CommandOnCooldown):
        await interaction.response.send_message("⏳ This command is on cooldown, please wait.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ An error occurred: {error}", ephemeral=True)
        print(f"Error in command {interaction.command}: {error}")
        traceback.print_exc()


@tasks.loop(time=time(hour=15, minute=36, second=0))  # 10 minutes before daily post
async def riddle_announcement():
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("Riddle announcement skipped: Channel not found.")
        return

    embed = discord.Embed(
        title="ℹ️ Upcoming Riddle Alert!",
        description="The next riddle will be submitted soon. Get ready!\n\n💡 Submit your own riddle using the `/submitriddle` command!",
        color=discord.Color.blurple()
    )

    await channel.send(embed=embed)


@tasks.loop(seconds=30)
async def daily_riddle_post():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    print(f"[LOOP ENTRY] id(db): {id(db)} at {db.__file__ if hasattr(db, '__file__') else 'unknown'}")
    print(f"[LOOP ENTRY] db.db_pool: {db.db_pool} (type={type(db.db_pool)})")

    try:
        print("DEBUG: daily_riddle_post started")
        print(f"[LOOP DEBUG] db module id: {id(db)} at {getattr(db, '__file__', 'unknown file')}")
        print(f"[LOOP DEBUG] db.db_pool id: {id(db.db_pool)} (None={db.db_pool is None})")

        if current_riddle is not None:
            print("DEBUG: Skipping because current_riddle already active")
            return

        channel_id_str = os.getenv("DISCORD_CHANNEL_ID")
        if not channel_id_str:
            print("ERROR: DISCORD_CHANNEL_ID env var not set or empty.")
            return
        try:
            channel_id = int(channel_id_str)
        except Exception as e:
            print(f"ERROR: Failed to convert DISCORD_CHANNEL_ID to int: {e}")
            return

        channel = client.get_channel(channel_id)
        print(f"DEBUG: Fetched channel object: {channel} (ID: {channel_id})")
        if not channel:
            print("ERROR: Daily riddle post skipped: Channel not found or not cached.")
            return

        riddles = await get_unused_questions()
        print(f"DEBUG: Retrieved {len(riddles)} unused riddles from DB")
        if not riddles:
            print("WARN: No riddles available to post.")
            return

        riddle = random.choice(riddles)
        print(f"DEBUG: Selected riddle ID {riddle['riddle_id']} for posting")
        current_riddle = riddle
        current_answer_revealed = False
        correct_users = set()
        guess_attempts = {}
        deducted_for_user = set()
        submitter_name = "Anonymous"
        if riddle.get("user_id"):
            user = client.get_user(int(riddle["user_id"]))
            if user:
                submitter_name = user.display_name
            print(f"DEBUG: Riddle submitted by user ID {riddle['user_id']} ({submitter_name})")
        else:
            print("DEBUG: Riddle has no user_id")

        embed = discord.Embed(
            title=f"🧩 Riddle of the Day #{riddle['riddle_id']}",
            description=f"**Riddle:** {riddle['question']}\n\n_(Riddle submitted by {submitter_name})_",
            color=discord.Color.blurple()
        )
        await channel.send(embed=embed)
        print(f"INFO: Posted daily riddle #{riddle['riddle_id']} to channel {channel.name} ({channel_id})")

        print(f"[ACQUIRE ATTEMPT] db.db_pool right before acquire: {db.db_pool} (type={type(db.db_pool)})")
        if db.db_pool is None:
            print("[ACQUIRE ERROR] db.db_pool is None right before acquire!")
            return
        async with db.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_submitted_questions SET posted_at = NOW() WHERE riddle_id = $1",
                riddle["riddle_id"]
            )
        print(f"DEBUG: Marked riddle #{riddle['riddle_id']} as posted in DB")

    except Exception as e:
        print(f"ERROR in daily_riddle_post loop: {e}")


@tasks.loop(seconds=45)  # Runs at 23:00 UTC daily
async def reveal_riddle_answer():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    try:
        if not current_riddle or current_answer_revealed:
            print("DEBUG: No active riddle or answer already revealed. Skipping reveal.")
            return

        channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
        channel = client.get_channel(channel_id)
        if not channel:
            print("Answer reveal skipped: Channel not found.")
            return

        answer = current_riddle.get("answer", "Unknown")
        riddle_id = current_riddle.get("riddle_id", "???")

        embed = discord.Embed(
            title=f"🔔 Answer to Riddle #{riddle_id}",
            description=f"**Answer:** {answer}\n\n💡 Use `/submitriddle` to submit your own riddle!",
            color=discord.Color.green()
        )
        await channel.send(embed=embed)

        if correct_users:
            all_scores = await db.get_all_scores()
            max_score = max(all_scores.values()) if all_scores else 0

            congrats_embed = discord.Embed(
                title="🎊 Congratulations to the following users who solved today's riddle! 🎊",
                color=discord.Color.gold()
            )
            description_lines = []
            for idx, user_id_str in enumerate(correct_users, start=1):
                try:
                    user = await client.fetch_user(int(user_id_str))
                    score_val = all_scores.get(user_id_str, 0)
                    streak_val = await db.get_streak(user_id_str)

                    score_line = f"{score_val}"
                    if score_val == max_score and max_score > 0:
                        score_line += " - 👑 🍣 Master Sushi Chef"

                    rank = get_rank(score_val, streak_val)
                    streak_line = f"🔥{streak_val}"

                    description_lines.append(f"#{idx} {user.display_name}:")
                    description_lines.append(f"    • Score: {score_line}")
                    description_lines.append(f"    • Rank: {rank}")
                    description_lines.append(f"    • Streak: {streak_line}")
                    description_lines.append("")
                except Exception:
                    description_lines.append(f"#{idx} <@{user_id_str}>")
                    description_lines.append("")

            congrats_embed.description = "\n".join(description_lines)
            await channel.send(embed=congrats_embed)
        else:
            await channel.send("😢 No one guessed the riddle correctly today.")

        user_id = current_riddle.get("user_id_id")

        all_streak_users = await db.get_all_streak_users()
        for user_id_str in all_streak_users:
            if user_id_str in correct_users:
                continue  # They got it right

            if user_id and user_id_str == str(user_id):
                continue  # Skip riddle submitter

            if user_id_str in deducted_for_user:
                continue  # Already penalized

    await db.adjust_score_and_reset_streak(user_id_str, -1)
    deducted_for_user.add(user_id_str)

        current_answer_revealed = True
        current_riddle = None
        correct_users.clear()
        guess_attempts.clear()
        deducted_for_user.clear()
    except Exception as e:
        print(f"ERROR in reveal_riddle_answer loop: {e}")


async def daily_riddle_post_callback():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    if current_riddle is not None:
        print("⛔ Skipping manual riddle post: one already exists.")
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("⚠️ Could not find channel for riddle post.")
        return

    riddles = await get_unused_questions()
    if not riddles:
        print("⛔ No riddles available to post.")
        return

    riddle = random.choice(riddles)
    current_riddle = riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    submitter_name = "Riddle of the day bot"
    if riddle.get("user_id"):
        user = client.get_user(int(riddle["user_id"]))
        if user:
            submitter_name = user.display_name

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{riddle['riddle_id']}",
        description=f"**Riddle:** {riddle['question']}\n\n_(Riddle submitted by {submitter_name})_",
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed)
    print(f"✅ Sent manual riddle post #{riddle['riddle_id']}.")


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")

    commands.setup(tree, client)
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    if not riddle_announcement.is_running():
        riddle_announcement.start()
    if not daily_riddle_post.is_running():
        daily_riddle_post.start()
    if not reveal_riddle_answer.is_running():
        reveal_riddle_answer.start()


async def run_bot():
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    DB_URL = os.getenv("DATABASE_URL")

    if not TOKEN or not DB_URL:
        print("ERROR: Required environment variables are not set.")
        exit(1)

    try:
        print("⏳ Connecting to the database...")
        pool = await db.create_db_pool()  # sets db.db_pool internally
        commands.set_db_pool(pool)         # sets commands.db_pool for commands.py usage
        print("✅ Database connection pool created successfully.")
    except Exception as e:
        print(f"❌ Failed to connect to the database: {e}")
        exit(1)

    await client.start(TOKEN)


asyncio.run(run_bot())
