# riddle_bot_upgraded.py

import discord
from discord.ext import tasks
from discord import app_commands
import asyncio
import json
import os
import re
import traceback
import random
from datetime import datetime, time, timezone, timedelta, date

# Import your separate module for test commands, make sure it exports the needed functions:
import test_sequence

# Constants for file names
QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"
SUBMISSION_DATES_FILE = "submission_dates.json"

# Bot intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Single client and command tree
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Global variables and state
submitted_questions = []
scores = {}
streaks = {}
submission_dates = {}
used_question_ids = set()
current_riddle = None
current_answer_revealed = False
correct_users = set()
guess_attempts = {}
deducted_for_user = set()
max_id = 0

NOTIFY_USER_ID = os.getenv("NOTIFY_USER_ID")
STOP_WORDS = {"a", "an", "the", "is", "was", "were", "of", "to", "and", "in", "on", "at", "by"}

# --- JSON Helpers ---
def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    # Return empty structures if file doesn't exist or fails
    if filename == QUESTIONS_FILE:
        return []
    else:
        return {}

def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving {filename}: {e}")

def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)
    save_json(SUBMISSION_DATES_FILE, submission_dates)

# --- Utility Functions ---
def clamp_min_zero(value):
    return max(0, value)

def get_rank(score, streak):
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

def clean_and_filter(text):
    words = re.findall(r'\b\w+\b', text.lower())
    return [w for w in words if w not in STOP_WORDS]

def count_unused_questions():
    return len([q for q in submitted_questions if q.get("id") not in used_question_ids])

def get_next_id():
    global max_id
    max_id += 1
    return str(max_id)

def pick_next_riddle():
    unused = [q for q in submitted_questions if q.get("id") not in used_question_ids and q.get("id") is not None]
    if not unused:
        used_question_ids.clear()
        unused = [q for q in submitted_questions if q.get("id") is not None]
    if not unused:
        return None
    riddle = random.choice(unused)
    used_question_ids.add(riddle["id"])
    return riddle

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

# Load all data on startup
def load_all_data():
    global submitted_questions, scores, streaks, submission_dates, max_id
    submitted_questions = load_json(QUESTIONS_FILE)
    scores = load_json(SCORES_FILE)
    streaks = load_json(STREAKS_FILE)
    submission_dates = load_json(SUBMISSION_DATES_FILE)

    existing_ids = [int(q["id"]) for q in submitted_questions if q.get("id") and str(q["id"]).isdigit()]
    max_id = max(existing_ids) if existing_ids else 0

load_all_data()
# --- Command and Event Definitions ---

# Sync commands on ready
@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# Test sequence command - admin/mod only
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
                    uid = str(user.id)
                    sv = scores.get(uid, 0)
                    st = streaks.get(uid, 0)
                    rank = get_rank(sv, st)
                    congrats_lines.append(f"{user.mention} — Score: **{sv}**, Streak: 🔥{st}, Rank: {rank}")
                except:
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

# Register test sequence command
setup_test_sequence_commands(tree, client)

# Addpoints command - admin/mod only
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

# Addstreak command - admin/mod only
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

# Removepoints command - admin/mod only
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

# Removestreak command - admin/mod only
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
# --- Riddle Submission Command ---

@tree.command(name="submitriddle", description="Submit a new riddle for the daily contest")
@app_commands.describe(question="The riddle question", answer="The answer to the riddle")
async def submitriddle(interaction: discord.Interaction, question: str, answer: str):
    global current_riddle
    if current_riddle is not None:
        await interaction.response.send_message("❌ There is already an active riddle. Please wait for it to finish.", ephemeral=True)
        return

    # Sanitize inputs (basic)
    question = question.strip()
    answer = answer.strip().lower()

    if len(question) == 0 or len(answer) == 0:
        await interaction.response.send_message("❌ Question and answer cannot be empty.", ephemeral=True)
        return

    # Assign an ID (simple incremental or from a stored counter)
    new_id = max([int(rid) for rid in riddles.keys()] + [0]) + 1
    new_id_str = str(new_id)

    current_riddle = {
        "id": new_id_str,
        "question": question,
        "answer": answer,
        "submitter_id": str(interaction.user.id)
    }
    global current_answer_revealed, correct_users, guess_attempts, deducted_for_user
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    # Store the riddle for persistence
    riddles[new_id_str] = current_riddle
    save_all_riddles()

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{new_id_str}",
        description=f"**Riddle:** {question}\n\n_(Riddle submitted by {interaction.user.display_name})_",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)

# --- Guess Command ---

@tree.command(name="guess", description="Submit your guess for the active riddle")
@app_commands.describe(guess="Your guess for the riddle answer")
async def guess(interaction: discord.Interaction, guess: str):
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    if current_riddle is None:
        await interaction.response.send_message("❌ There is no active riddle right now.", ephemeral=True)
        return

    if current_answer_revealed:
        await interaction.response.send_message("❌ The answer has already been revealed for this riddle.", ephemeral=True)
        return

    uid = str(interaction.user.id)

    # Track guess attempts per user
    guess_attempts[uid] = guess_attempts.get(uid, 0) + 1

    normalized_guess = guess.strip().lower()
    correct_answer = current_riddle['answer'].lower()

    if normalized_guess == correct_answer:
        if uid in correct_users:
            await interaction.response.send_message("✅ You already guessed correctly!", ephemeral=True)
            return

        correct_users.add(uid)
        # Award points and streak
        scores[uid] = scores.get(uid, 0) + 10  # example points
        streaks[uid] = streaks.get(uid, 0) + 1
        save_all_scores()

        embed = discord.Embed(
            title="Correct Guess! 🎉",
            description=f"Congratulations {interaction.user.mention}, you guessed the riddle correctly!\nYou earned 10 points and your streak increased by 1.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    else:
        # Penalize guess attempts (optional)
        if uid not in deducted_for_user:
            scores[uid] = max(0, scores.get(uid, 0) - 1)
            deducted_for_user.add(uid)
            save_all_scores()

        embed = discord.Embed(
            title="Incorrect Guess ❌",
            description=f"Sorry {interaction.user.mention}, that is not the correct answer.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)

# --- Helper Functions ---

def save_all_scores():
    # Implement your persistence logic here, e.g., JSON file write
    with open("scores.json", "w") as f:
        json.dump({"scores": scores, "streaks": streaks}, f)

def save_all_riddles():
    with open("riddles.json", "w") as f:
        json.dump(riddles, f)

def load_all_data():
    global scores, streaks, riddles
    try:
        with open("scores.json", "r") as f:
            data = json.load(f)
            scores = data.get("scores", {})
            streaks = data.get("streaks", {})
    except FileNotFoundError:
        scores = {}
        streaks = {}

    try:
        with open("riddles.json", "r") as f:
            riddles.update(json.load(f))
    except FileNotFoundError:
        riddles.clear()

def get_rank(score, streak):
    # Example rank calculation, customize as needed
    if score >= 100 and streak >= 10:
        return "Riddle Master"
    elif score >= 50:
        return "Riddle Expert"
    elif score >= 20:
        return "Riddle Apprentice"
    else:
        return "Riddle Novice"

# Initialize global data containers
scores = {}
streaks = {}
riddles = {}

# Load data on bot start
load_all_data()
current_riddle = None
current_answer_revealed = False
correct_users = set()
guess_attempts = {}
deducted_for_user = set()
# --- Event Listeners ---

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

@client.event
async def on_ready():
    print(f"Bot logged in as {client.user} (ID: {client.user.id})")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# --- Scheduled Daily Riddle Posting (Optional) ---

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

    # Pick a riddle to post (example: random from riddles dict)
    if not riddles:
        print("No riddles available to post.")
        return

    riddle_id, riddle = random.choice(list(riddles.items()))
    current_riddle = riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{riddle_id}",
        description=f"**Riddle:** {riddle['question']}\n\n_(Riddle submitted by {client.get_user(int(riddle['submitter_id'])).display_name if riddle['submitter_id'] else 'Anonymous'})_",
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed)

    print(f"Posted daily riddle #{riddle_id}")

# To start the daily riddle posting loop (uncomment in main startup)
# daily_riddle_post.start()

# --- Utility Function ---

def clamp_min_zero(value):
    return max(0, value)

# --- Main Bot Run ---

if __name__ == "__main__":
    import os

    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN environment variable is not set.")
        exit(1)

    client.run(TOKEN)


