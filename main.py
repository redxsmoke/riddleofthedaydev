import discord
from discord.ext import tasks
from discord import app_commands, Interaction, Embed
from discord.ui import View, Button
import asyncio
import json
import os
import re
import random
import traceback
from datetime import datetime, timezone, time
from views import LeaderboardView, create_leaderboard_embed
from db import create_db_pool, upsert_user, get_user, insert_submitted_question, get_all_submitted_questions





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

@tree.command(name="myranks", description="Show your riddle score, streak, and rank")
async def myranks(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    score_val = scores.get(user_id, 0)
    streak_val = streaks.get(user_id, 0)
    rank = get_rank(score_val)
    streak_rank = get_streak_rank(streak_val)

    embed = discord.Embed(
        title=f"📊 Your Riddle Stats, {interaction.user.display_name}",
        color=discord.Color.green()
    )

    score_text = f"Score: {score_val} {'🍣' if score_val > 0 else ''}"
    streak_text = f"Streak: 🔥{streak_val}"
    if streak_rank:
        streak_text += f" — {streak_rank}"

    embed.add_field(name="Score", value=score_text, inline=False)
    embed.add_field(name="Streak", value=streak_text, inline=False)
    embed.add_field(name="Rank", value=rank or "No rank", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)






def ensure_user_initialized(uid: str):
    # Initialize user data if missing
    if uid not in scores:
        scores[uid] = 0
    if uid not in streaks:
        streaks[uid] = 0
    if uid not in submission_dates:
        submission_dates[uid] = None



@tree.command(name="ranks", description="View all rank tiers and how to earn them")
async def ranks(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📊 Riddle Rank Tiers",
        description="Earn score and build streaks to level up your riddle mastery!",
        color=discord.Color.purple()
    )

    embed.add_field(
        name="👑 Top Rank",
        value="**🍣 Master Sushi Chef** — Awarded to the user(s) with the highest score.",
        inline=False
    )

    embed.add_field(
        name="🔥 Streak-Based Titles",
        value=(
            "• 🔥 **Streak Samurai** — 3-day streak\n"
            "• 🍤 **Tempura Titan** — 5-day streak\n"
            "• 🍣 **Nigiri Ninja** — 10-day streak\n"
            "• 🥢 **Rollmaster Ronin** — 20-day streak\n"
            "• 💚🔥 **Wasabi Warlord** — 30+ day streak"
        ),
        inline=False
    )

    embed.add_field(
        name="🎯 Score-Based Ranks",
        value=(
            "• 🍽️ **Sushi Newbie** — 0–5 points\n"
            "• 🍣 **Maki Novice** — 6–15 points\n"
            "• 🍤 **Sashimi Skilled** — 16–25 points\n"
            "• 🧠 **Brainy Botan** — 26–50 points\n"
            "• 🧪 **Sushi Einstein** — 51+ points"
        ),
        inline=False
    )

    embed.set_footer(text="Ranks update automatically based on your progress.")
    await interaction.response.send_message(embed=embed)



def get_rank(score):
    if score <= 5:
        return "🍽️ Sushi Newbie"
    elif 6 <= score <= 15:
        return "🍣 Maki Novice"
    elif 16 <= score <= 25:
        return "🍤 Sashimi Skilled"
    elif 26 <= score <= 50:
        return "🧠 Brainy Botan"
    else:
        return "🧪 Sushi Einstein"

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
        return None  # No title




@tree.command(name="removeriddle", description="Remove a riddle by its number (ID)")
@app_commands.describe(riddle_id="The ID number of the riddle to remove")
@app_commands.checks.has_permissions(manage_guild=True)
async def removeriddle(interaction: discord.Interaction, riddle_id: int):
    global submitted_questions, used_question_ids

    # Convert ID to string to match stored riddles
    riddle_id_str = str(riddle_id)

    # Find riddle index by ID
    index_to_remove = next((i for i, r in enumerate(submitted_questions) if str(r.get("id")) == riddle_id_str), None)

    if index_to_remove is None:
        await interaction.response.send_message(f"❌ No riddle found with ID #{riddle_id}.", ephemeral=True)
        return

    # Remove riddle
    removed_riddle = submitted_questions.pop(index_to_remove)
    used_question_ids.discard(riddle_id_str)

    # Save changes
    save_all_riddles()

    await interaction.response.send_message(f"✅ Removed riddle #{riddle_id}: {removed_riddle.get('question')}", ephemeral=True)

ITEMS_PER_PAGE = 10

class ListRiddlesView(View):
    def __init__(self, riddles, author_id, bot):
        super().__init__(timeout=180)
        self.riddles = riddles
        self.author_id = author_id
        self.current_page = 0
        self.total_pages = max(1, (len(riddles) - 1) // ITEMS_PER_PAGE + 1)
        self.bot = bot  # save bot/client to fetch users
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    async def get_page_embed(self):
        start = self.current_page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_riddles = self.riddles[start:end]

        embed = Embed(
            title=f"📜 Submitted Riddles (Page {self.current_page + 1}/{self.total_pages})",
            color=discord.Color.blurple()
        )

        if not page_riddles:
            embed.description = "No riddles available."
            return embed

        desc_lines = []
        for riddle in page_riddles:
            try:
                user = await self.bot.fetch_user(int(riddle['submitter_id']))
                display_name = user.display_name if hasattr(user, 'display_name') else user.name
            except Exception:
                display_name = "Unknown User"
            desc_lines.append(f"#{riddle['id']}: {riddle['question']}\n_(submitted by {display_name})_")

        embed.description = "\n\n".join(desc_lines)
        embed.set_footer(text="Use the buttons below to navigate pages.")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = await self.get_page_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = await self.get_page_embed()
            await interaction.response.edit_message(embed=embed, view=self)


@tree.command(name="listriddles", description="List all submitted riddles with pagination")
async def listriddles(interaction: discord.Interaction):
    if not submitted_questions:
        await interaction.response.send_message("No riddles have been submitted yet.", ephemeral=True)
        return

    view = ListRiddlesView(submitted_questions, interaction.user.id, interaction.client)
    embed = await view.get_page_embed()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)



@tree.command(name="leaderboard", description="Show the riddle leaderboard with pagination")
async def leaderboard(interaction: Interaction):
    await interaction.response.defer()

    # Filter users with score or streak >= 1
    filtered_users = [user_id for user_id in scores.keys() if (scores.get(user_id, 0) >= 1 or streaks.get(user_id, 0) >= 1)]

    if not filtered_users:
        await interaction.followup.send("No leaderboard data available.", ephemeral=True)
        return

    # Sort users descending by (score, streak)
    filtered_users.sort(key=lambda u: (scores.get(u, 0), streaks.get(u, 0)), reverse=True)

    view = LeaderboardView(client, filtered_users, per_page=10)
    # Initial send
    start = 0
    end = 10
    initial_users = filtered_users[start:end]

    embed = Embed(
        title=f"🏆 Riddle Leaderboard (Page 1 / {(len(filtered_users) - 1) // 10 + 1})",
        color=discord.Color.gold()
    )

    description_lines = []
    max_score = max((scores.get(u, 0) for u in filtered_users), default=0)

    for idx, user_id_str in enumerate(initial_users, start=1):
        try:
            user = await client.fetch_user(int(user_id_str))
            score_val = scores.get(user_id_str, 0)
            streak_val = streaks.get(user_id_str, 0)

            score_line = f"{score_val}"
            if score_val == max_score and max_score > 0:
                score_line += " - 👑 🍣 Master Sushi Chef"

            rank = get_rank(score_val)
            streak_rank = get_streak_rank(streak_val)
            streak_text = f"🔥{streak_val}"
            if streak_rank:
                streak_text += f" - {streak_rank}"

            description_lines.append(f"#{idx} {user.display_name}:")
            description_lines.append(f"    • Score: {score_line}")
            description_lines.append(f"    • Rank: {rank}")
            description_lines.append(f"    • Streak: {streak_text}")
            description_lines.append("")
        except Exception:
            description_lines.append(f"#{idx} <@{user_id_str}> (failed to fetch user)")
            description_lines.append("")

    embed.description = "\n".join(description_lines) or "No users to display."

    await interaction.followup.send(embed=embed, view=view)




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

@tasks.loop(time=time(hour=11, minute=50, second=0))  # 10 minutes before daily post
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

from datetime import timedelta

@tasks.loop(time=time(hour=23, minute=0, second=0))  # Runs at 23:00 UTC daily
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
        max_score = max(scores.values()) if scores else 0
        congrats_embed = discord.Embed(
            title="🎊 Congratulations to the following users who solved today's riddle! 🎊",
            color=discord.Color.gold()
        )
        description_lines = []
        for idx, user_id_str in enumerate(correct_users, start=1):
            try:
                user = await client.fetch_user(int(user_id_str))
                score_val = scores.get(user_id_str, 0)
                streak_val = streaks.get(user_id_str, 0)

                score_line = f"{score_val}"
                if score_val == max_score and max_score > 0:
                    score_line += " - 👑 🍣 Master Sushi Chef"

                rank = get_rank(score_val)
                streak_rank = get_streak_rank(streak_val)
                streak_line = f"🔥{streak_val}"
                if streak_rank:
                    streak_line += f" - {streak_rank}"

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

    for user_id_str in list(streaks.keys()):
        # Skip users who got it correct
        if user_id_str in correct_users:
            continue

        # Skip if user is today's riddle submitter
        if submitter_id and user_id_str == str(submitter_id):
            continue

        # If the user made 0 attempts, reset their streak
        if user_id_str not in guess_attempts:
            streaks[user_id_str] = 0

    save_all_scores()

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
    await create_db_pool()
    print(f"Bot logged in as {client.user} (ID: {client.user.id})")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # <<< ADD THESE LINES RIGHT HERE >>>
    daily_riddle_post.start()
    riddle_announcement.start()
    reveal_riddle_answer.start()
 

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN environment variable is not set.")
        exit(1)



    client.run(TOKEN)
    
