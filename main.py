import discord
from discord import app_commands
from discord.ext import tasks
from discord import Interaction, Embed
from discord.ui import View, Button
import commands
import os
import re
import random
import traceback
from datetime import datetime, timezone, time, timedelta
from views import LeaderboardView, create_leaderboard_embed
from db import create_db_pool, upsert_user, get_user, insert_submitted_question, get_all_submitted_questions
import asyncio

import asyncpg
import db
from commands import setup, set_db_pool  # make sure setup is exported


# Only one intents declaration (fixed duplicate)
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

 



STOP_WORDS = {"a", "an", "the", "is", "was", "were", "of", "to", "and", "in", "on", "at", "by"}

def clean_and_filter(text):
    words = re.findall(r'\b\w+\b', text.lower())
    return [w for w in words if w not in STOP_WORDS]




def format_question_embed(qdict, submitter=None):
    embed = discord.Embed(
        title=f"🧠 Riddle #{qdict['id']}",
        description=qdict['question'],
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Answer will be revealed at 23:00 UTC. Use /submitriddle to contribute your own!")

    remaining = count_unused_questions()
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
    # scores is no longer global, so only use parameters
    if score > 0:
        # Master Sushi Chef only if top score - can only do this externally now, so keep rank logic simple here
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

    # If no riddle is active or it's already revealed, ignore all messages (they're not guesses)
    if not current_riddle or current_answer_revealed:
        return

    # Only block submitter IF the active riddle is theirs AND they are trying to guess it
    if current_riddle.get("submitter_id") == user_id:
        user_words = clean_and_filter(content)
        answer_words = clean_and_filter(current_riddle["answer"])

        # Only block if it looks like an answer attempt
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

    # If they've already answered correctly, ignore further guesses
    if user_id in correct_users:
        try: await message.delete()
        except: pass
        await message.channel.send(
            f"✅ You already answered correctly, {message.author.mention}. No more guesses counted.",
            delete_after=5
        )
        return

    # Track how many guesses they’ve made
    attempts = guess_attempts.get(user_id, 0)
    if attempts >= 5:
        try: await message.delete()
        except: pass
        await message.channel.send(
            f"❌ You are out of guesses for this riddle, {message.author.mention}.",
            delete_after=5
        )
        return

    # Record this guess
    guess_attempts[user_id] = attempts + 1

    # Check answer words
    user_words = clean_and_filter(content)
    answer_words = clean_and_filter(current_riddle["answer"])
    
    if any(word in user_words for word in answer_words):
        # Correct
        correct_users.add(user_id)
        await db.increment_score(user_id)
        await db.increment_streak(user_id)

        # Get updated values to show in embed
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
        # Wrong
        remaining = 5 - guess_attempts.get(user_id, 0)
        if remaining == 0 and user_id not in deducted_for_user:
            # Penalty on 5th wrong guess
            await db.decrement_score(user_id)     # Implement in db.py
            await db.reset_streak(user_id)        # Implement in db.py
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

    # Send countdown until reveal
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

@tasks.loop(time=time(hour=15, minute=36, second=0))  # Posts every day at noon UTC
async def daily_riddle_post():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    if current_riddle is not None:
        # There is already an active riddle; skip
        return

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("Daily riddle post skipped: Channel not found.")
        return

    if not submitted_questions:
        print("No riddles available to post.")
        return

    riddle = random.choice(submitted_questions)
    current_riddle = riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()
    submitter_name = "Anonymous"
    if riddle.get("submitter_id"):
        user = client.get_user(int(riddle["submitter_id"]))
        if user:
            submitter_name = user.display_name

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{riddle['id']}",
        description=f"**Riddle:** {riddle['question']}\n\n_(Riddle submitted by {submitter_name})_",
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed)

    print(f"Posted daily riddle #{riddle['id']}")

@tasks.loop(time=time(hour=15, minute=38, second=0))  # Runs at 23:00 UTC daily
async def reveal_riddle_answer():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    if not current_riddle or current_answer_revealed:
        return  # Nothing to reveal

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        print("Answer reveal skipped: Channel not found.")
        return

    answer = current_riddle.get("answer", "Unknown")
    riddle_id = current_riddle.get("id", "???")

    # Post the answer
    embed = discord.Embed(
        title=f"🔔 Answer to Riddle #{riddle_id}",
        description=f"**Answer:** {answer}\n\n💡 Use `/submitriddle` to submit your own riddle!",
        color=discord.Color.green()
    )
    await channel.send(embed=embed)

    # Post congratulations
    if correct_users:
        # Get all user scores from DB for max calculation
        all_scores = await db.get_all_scores()  # You must implement this in db.py returning {user_id: score}
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

    # ✅ Streak reset for users who did not guess and are not the submitter
    submitter_id = current_riddle.get("submitter_id")

    all_streak_users = await db.get_all_streak_users()  # Implement in db.py returning list of user_ids with streaks
    for user_id_str in all_streak_users:
        # Skip users who got it correct
        if user_id_str in correct_users:
            continue

        # Skip if user is today's riddle submitter
        if submitter_id and user_id_str == str(submitter_id):
            continue

        # If the user made 0 attempts, reset their streak
        if user_id_str not in guess_attempts:
            await db.reset_streak(user_id_str)

    # ✅ Reset state
    current_answer_revealed = True
    current_riddle = None
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()

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

    if not submitted_questions:
        print("⛔ No riddles available to post.")
        return

    riddle = pick_next_riddle()
    current_riddle = riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    submitter_name = "Riddle of the day bot"
    if riddle.get("submitter_id"):
        user = client.get_user(int(riddle["submitter_id"]))
        if user:
            submitter_name = user.display_name

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{riddle['id']}",
        description=f"**Riddle:** {riddle['question']}\n\n_(Riddle submitted by {submitter_name})_",
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed)
    print(f"✅ Sent manual riddle post #{riddle['id']}.")

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    
    commands.setup(tree, client)   # setup commands after login
    try:
        synced = await tree.sync()  # sync commands after client ready
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    if not riddle_announcement.is_running():
        riddle_announcement.start()
    if not daily_riddle_post.is_running():
        daily_riddle_post.start()
    if not reveal_riddle_answer.is_running():
        reveal_riddle_answer.start()


async def startup():
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    DB_URL = os.getenv("DATABASE_URL")

    if not TOKEN or not DB_URL:
        print("ERROR: Required environment variables are not set.")
        exit(1)

    try:
        print("⏳ Connecting to the database...")
        pool = await db.create_db_pool()
        commands.set_db_pool(pool)
        print("✅ Database connection pool created successfully.")

  
    except Exception as e:
        print(f"❌ Failed to connect to the database or sync commands: {e}")
        exit(1)

    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(startup())

