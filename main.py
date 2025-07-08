import discord
from discord.ext import tasks
from discord import app_commands
import asyncio
import json
import os
import re
import random
import traceback
from datetime import datetime, timezone, time


# Constants for file names
QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"
SUBMISSION_DATES_FILE = "submission_dates.json"

# Bot intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Global state containers
submitted_questions = []    # List of dicts with riddles, each with id, question, answer, submitter_id
scores = {}                 # user_id (str) -> int score
streaks = {}                # user_id (str) -> int streak count
submission_dates = {}       # user_id (str) -> str date (YYYY-MM-DD) for tracking submissions
used_question_ids = set()   # Set of str IDs used recently

current_riddle = None       # Currently active riddle dict or None
current_answer_revealed = False
correct_users = set()       # user_ids who guessed right this round
guess_attempts = {}         # user_id -> int attempts count for current riddle
deducted_for_user = set()   # user_ids deducted penalty for wrong guess in current riddle

max_id = 0                  # For generating new IDs (incremental)


# Utility: Clamp value to zero minimum
def clamp_min_zero(value):
    return max(0, value)


# Load JSON file or return default empty data
def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    # Return defaults
    if filename == QUESTIONS_FILE:
        return []
    else:
        return {}


# Save data to JSON file
def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving {filename}: {e}")


# Load all persistent data on bot start
def load_all_data():
    global submitted_questions, scores, streaks, submission_dates, max_id

    submitted_questions = load_json(QUESTIONS_FILE)
    scores = load_json(SCORES_FILE)
    streaks = load_json(STREAKS_FILE)
    submission_dates = load_json(SUBMISSION_DATES_FILE)

    # Determine max ID for new riddle submissions
    existing_ids = []
    for q in submitted_questions:
        if "id" in q and str(q["id"]).isdigit():
            existing_ids.append(int(q["id"]))
    max_id = max(existing_ids) if existing_ids else 0


# Save all score and streak data
def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)
    save_json(SUBMISSION_DATES_FILE, submission_dates)


# Save all riddles/questions
def save_all_riddles():
    save_json(QUESTIONS_FILE, submitted_questions)


# Call load on startup
load_all_data()

def get_next_id():
    global max_id
    max_id += 1
    return str(max_id)


def pick_next_riddle():
    unused = [q for q in submitted_questions if str(q.get("id")) not in used_question_ids and q.get("id") is not None]
    if not unused:
        used_question_ids.clear()
        unused = [q for q in submitted_questions if q.get("id") is not None]
    if not unused:
        return None
    riddle = random.choice(unused)
    used_question_ids.add(str(riddle["id"]))
    return riddle
STOP_WORDS = {"a", "an", "the", "is", "was", "were", "of", "to", "and", "in", "on", "at", "by"}

def clean_and_filter(text):
    words = re.findall(r'\b\w+\b', text.lower())
    return [w for w in words if w not in STOP_WORDS]


def count_unused_questions():
    return len([q for q in submitted_questions if str(q.get("id")) not in used_question_ids])


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


def get_rank(score, streak):
    # Example rank calculation, customize as needed
    if scores:
        max_score = max(scores.values())
        if score == max_score and max_score > 0:
            return "🍣 Master Sushi Chef (Top scorer)"
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
@tree.command(name="submitriddle", description="Submit a new riddle for the daily contest")
@app_commands.describe(question="The riddle question", answer="The answer to the riddle")
async def submitriddle(interaction: discord.Interaction, question: str, answer: str):
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    if current_riddle is not None:
        await interaction.response.send_message("❌ There is already an active riddle. Please wait for it to finish.", ephemeral=True)
        return

    question = question.strip()
    answer = answer.strip().lower()

    if not question or not answer:
        await interaction.response.send_message("❌ Question and answer cannot be empty.", ephemeral=True)
        return

    new_id = get_next_id()
    new_riddle = {
        "id": new_id,
        "question": question,
        "answer": answer,
        "submitter_id": str(interaction.user.id),
    }
    submitted_questions.append(new_riddle)
    save_all_riddles()

    current_riddle = new_riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{new_id}",
        description=f"**Riddle:** {question}\n\n_(Riddle submitted by {interaction.user.display_name})_",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="addpoints", description="Add points to a user")
@app_commands.describe(user="The user to add points to", amount="Number of points to add (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def addpoints(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    scores[uid] = scores.get(uid, 0) + amount
    save_all_scores()
    await interaction.response.send_message(f"✅ Added {amount} point(s) to {user.mention}. New score: {scores[uid]}", ephemeral=True)


@tree.command(name="addstreak", description="Add streak days to a user")
@app_commands.describe(user="The user to add streak days to", amount="Number of streak days to add (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def addstreak(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    streaks[uid] = streaks.get(uid, 0) + amount
    save_all_scores()
    await interaction.response.send_message(f"✅ Added {amount} streak day(s) to {user.mention}. New streak: {streaks[uid]}", ephemeral=True)


@tree.command(name="removepoints", description="Remove points from a user")
@app_commands.describe(user="The user to remove points from", amount="Number of points to remove (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def removepoints(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    new_score = clamp_min_zero(scores.get(uid, 0) - amount)
    scores[uid] = new_score
    save_all_scores()
    await interaction.response.send_message(f"❌ Removed {amount} point(s) from {user.mention}. New score: {scores[uid]}", ephemeral=True)


@tree.command(name="leaderboard", description="Show the top scores and streaks")
async def leaderboard(interaction: discord.Interaction):
    # Sort top 10 by score descending
    top_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    # Sort top 10 by streak descending
    top_streaks = sorted(streaks.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 Riddle Leaderboard",
        color=discord.Color.gold()
    )

    score_lines = []
    for idx, (user_id, score_val) in enumerate(top_scores, start=1):
        user = await client.fetch_user(int(user_id))
        score_lines.append(f"#{idx} — {user.display_name}: **{score_val}** points")

    streak_lines = []
    for idx, (user_id, streak_val) in enumerate(top_streaks, start=1):
        user = await client.fetch_user(int(user_id))
        streak_lines.append(f"#{idx} — {user.display_name}: 🔥 **{streak_val}** day streak")

    embed.add_field(name="Top Scores", value="\n".join(score_lines) if score_lines else "No scores yet.", inline=True)
    embed.add_field(name="Top Streaks", value="\n".join(streak_lines) if streak_lines else "No streaks yet.", inline=True)

    await interaction.response.send_message(embed=embed)


@tree.command(name="removestreak", description="Remove streak days from a user")
@app_commands.describe(user="The user to remove streak days from", amount="Number of streak days to remove (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def removestreak(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return
    uid = str(user.id)
    new_streak = clamp_min_zero(streaks.get(uid, 0) - amount)
    streaks[uid] = new_streak
    save_all_scores()
    await interaction.response.send_message(f"❌ Removed {amount} streak day(s) from {user.mention}. New streak: {streaks[uid]}", ephemeral=True)
def setup_test_sequence_commands(tree, client):
    @tree.command(name="run_test_sequence", description="Run a full test riddle workflow")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def run_test_sequence(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
        channel = client.get_channel(channel_id)
        if not channel:
            await interaction.followup.send("❌ Test failed: Channel not found.", ephemeral=True)
            return

        global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

        current_riddle = {
            "id": "9999",
            "question": "What has keys but can't open locks?",
            "answer": "piano",
            "submitter_id": None,
        }
        current_answer_revealed = False
        correct_users = set()
        guess_attempts = {}
        deducted_for_user = set()

        embed = discord.Embed(
            title=f"🧩 Riddle of the Day #{current_riddle['id']}",
            description=f"**Riddle:** {current_riddle['question']}\n\n_(Riddle submitted by **Riddle of the Day Bot**)_",
            color=discord.Color.blurple()
        )
        await channel.send(embed=embed)

        await interaction.followup.send("✅ Test riddle posted. Waiting 30 seconds before revealing answer...", ephemeral=True)

        await asyncio.sleep(30)

        answer_embed = discord.Embed(
            title=f"🔔 Answer to Riddle #{current_riddle['id']}",
            description=f"**Answer:** {current_riddle['answer']}\n\n💡 Use `/submitriddle` to submit your own riddle!",
            color=discord.Color.green()
        )
        await channel.send(embed=answer_embed)

        if correct_users:
            congrats_lines = []
            for user_id_str in correct_users:
                try:
                    user = await client.fetch_user(int(user_id_str))
                    sv = scores.get(str(user.id), 0)
                    st = streaks.get(str(user.id), 0)
                    rank = get_rank(sv, st)
                    congrats_lines.append(f"{user.mention} — Score: **{sv}**, Streak: 🔥{st}, Rank: {rank}")
                except Exception:
                    congrats_lines.append(f"<@{user_id_str}>")
            congrats_msg = "🎉 Congratulations to:\n" + "\n".join(congrats_lines)
            await channel.send(congrats_msg)
        else:
            await channel.send("😢 No one guessed the riddle correctly during the test.")

        current_answer_revealed = True
        correct_users.clear()
        guess_attempts.clear()
        deducted_for_user.clear()
        current_riddle = None

        await channel.send("✅ Test sequence completed. You can run `/run_test_sequence` again to test.")

setup_test_sequence_commands(tree, client)

@client.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return

    # Only listen in the designated riddle channel
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    if message.channel.id != ch_id:
        return

    global correct_users, guess_attempts, deducted_for_user, current_riddle, current_answer_revealed

    user_id = str(message.author.id)
    content = message.content.strip()

    # No active riddle or already revealed
    if not current_riddle or current_answer_revealed:
        return

    # Submitter cannot answer and doesn't lose streak
    if current_riddle.get("submitter_id") == user_id:
        try: await message.delete()
        except: pass
        await message.channel.send(
            "⛔ You submitted this riddle and cannot answer it.",
            delete_after=10
        )
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
        scores[user_id] = scores.get(user_id, 0) + 1
        streaks[user_id] = streaks.get(user_id, 0) + 1
        save_all_scores()
        try: await message.delete()
        except: pass
        await message.channel.send(
            f"🎉 Correct, {message.author.mention}! Your total score: {scores[user_id]}"
        )
    else:
        # Wrong
        remaining = 5 - guess_attempts[user_id]
        if remaining == 0 and user_id not in deducted_for_user:
            # Penalty on 5th wrong guess
            scores[user_id] = max(0, scores.get(user_id, 0) - 1)
            streaks[user_id] = 0
            deducted_for_user.add(user_id)
            save_all_scores()
            await message.channel.send(
                f"❌ Incorrect, {message.author.mention}. You've used all guesses and lost 1 point.",
                delete_after=8
            )
        elif remaining > 0:
            await message.channel.send(
                f"❌ Incorrect, {message.author.mention}. {remaining} guess(es) left.",
                delete_after=6
            )
        try: await message.delete()
        except: pass

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
async def on_ready():
    print(f"Bot logged in as {client.user} (ID: {client.user.id})")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


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


@tasks.loop(time=time(hour=12, minute=0, second=0))  # Posts every day at noon UTC
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

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN environment variable is not set.")
        exit(1)

    client.run(TOKEN)

