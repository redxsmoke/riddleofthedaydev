import discord
from discord import app_commands
from discord.ext import tasks
from discord import Interaction, Embed
from discord.ui import View, Button

import json
import os
import re
import random
import traceback
from datetime import datetime, timezone, time, timedelta
from views import LeaderboardView, create_leaderboard_embed
from db import create_db_pool, upsert_user, get_user, insert_submitted_question, get_all_submitted_questions
import asyncio
from commands import setup, set_db_pool  # make sure setup is exported
import asyncpg

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# Constants for file names
QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE = "scores.json"
STREAKS_FILE = "streaks.json"
SUBMISSION_DATES_FILE = "submission_dates.json"


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


def get_rank(score, streak=0):
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


def get_streak_rank(streak):
    if streak >= 30:
        return "💚🔥 Wasabi Warlord"
    elif streak >= 20:
        return "🥢 Rollmaster Ronin"
    elif streak >= 10:
        return "🍣 Nigiri Ninja"
    elif streak >= 5:
        return "🍤 Tempura Titan"
    elif streak >= 3:
        return "🔥 Streak Samurai"
    else:
        return None


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
        try:
            await message.delete()
        except:
            pass
        await message.channel.send(
            f"✅ You already answered correctly, {message.author.mention}. No more guesses counted.",
            delete_after=5
        )
        return

    # Track how many guesses they’ve made
    attempts = guess_attempts.get(user_id, 0)
    if attempts >= 5:
        try:
            await message.delete()
        except:
            pass
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
        try:
            await message.delete()
        except:
            pass
        correct_guess_embed = discord.Embed(
            title="You guess correctly!",
            description=f"🥳 Correct, {message.author.mention}! Your total score: {scores[user_id]}",
            color=discord.Color.green()
        )
        await message.channel.send(embed=correct_guess_embed)
    else:
        # Wrong
        remaining = 5 - guess_attempts.get(user_id, 0)
        if remaining == 0 and user_id not in deducted_for_user:
            # Pena
