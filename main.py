import discord
from discord.ext import tasks
import asyncio
import json
import os
import re
NOTIFY_USER_ID = os.getenv("NOTIFY_USER_ID")
STOP_WORDS = {"a", "an", "the", "is", "was", "were", "of", "to", "and", "in", "on", "at", "by"}
def clean_and_filter(text):
    words = re.findall(r'\b\w+\b', text.lower())
    return [w for w in words if w not in STOP_WORDS]
    
from datetime import datetime, time, timezone, timedelta, date
import random
from discord import app_commands



# —– Intents + Client initialization —–
intents = discord.Intents.default()
intents.members = True            # so guild.members is populated
intents.message_content = True    # if you need to read message content

client = discord.Client(intents=intents)
tree   = app_commands.CommandTree(client)

QUESTIONS_FILE = "submitted_questions.json"
SCORES_FILE   = "scores.json"
STREAKS_FILE = "streaks.json"

submitted_questions = []
scores = {}
streaks = {}

used_question_ids = set()
current_riddle = None
current_answer_revealed = False
correct_users = set()
guess_attempts = {}  # user_id -> guesses this riddle
deducted_for_user = set()  # users who lost 1 point this riddle

max_id = 0  # tracks max numeric ID assigned

submission_dates = {}  # user_id -> date of last submission point awarded


# --- Helper functions ---

def load_json(file):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return [] if file == QUESTIONS_FILE else {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def save_all_scores():
    save_json(SCORES_FILE, scores)
    save_json(STREAKS_FILE, streaks)

def get_rank(score, streak):
    # Determine if user is Master Sushi Chef (top scorer) with sushi emoji 🍣
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

def count_unused_questions():
    return len([q for q in submitted_questions if q.get("id") not in used_question_ids])

def pick_next_riddle():
    unused = [q for q in submitted_questions if q.get("id") not in used_question_ids and q.get("id") is not None]
    if not unused:
        used_question_ids.clear()
        unused = [q for q in submitted_questions if q.get("id") is not None]
    riddle = random.choice(unused)
    used_question_ids.add(riddle["id"])
    return riddle

def format_question_text(qdict):
    base = f"{qdict['id']}. {qdict['question']} ***(Answer will be revealed at 23:00 UTC)***"
    
    # Add submitter mention if available
    if "submitter_id" in qdict:
        try:
            submitter = client.get_user(int(qdict["submitter_id"]))
            if submitter:
                base += f"\n_(Riddle submitted by {submitter.mention})_"
        except Exception as e:
            print(f"Could not fetch submitter for riddle {qdict['id']}: {e}")

    remaining = count_unused_questions()
    if remaining < 5:
        base += "\n\n⚠️ Less than 5 new riddles remain - submit a new riddle with /submitriddle to add it to the queue!"

    # Always append this line
    base += "\n\n💡 Use the `/submitriddle` command to submit your own riddle!"
    
    return base

def get_next_id():
    global max_id
    max_id += 1
    return str(max_id)


# --- Load data and initialize max_id ---
submitted_questions = load_json(QUESTIONS_FILE)
scores = load_json(SCORES_FILE)
streaks = load_json(STREAKS_FILE)

# Initialize max_id from existing question IDs (assuming numeric IDs)
existing_ids = [int(q["id"]) for q in submitted_questions if q.get("id") and str(q["id"]).isdigit()]
max_id = max(existing_ids) if existing_ids else 0


# --- /listriddlecommand ---
class QuestionListView(discord.ui.View):
    def __init__(self, user_id, questions, per_page=10):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.questions = questions
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(questions) - 1) // per_page + 1 if questions else 1

    def get_page_content(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_questions = self.questions[start:end]
        lines = [f"📋 Total riddles: {len(self.questions)}"]
        for q in page_questions:
            qid = q.get("id", "NA")
            lines.append(f"{qid}. {q['question']}")
        return "\n".join(lines)

    async def update_message(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This pagination isn't for you.", ephemeral=True)
            return
        await interaction.response.edit_message(content=self.get_page_content(), view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)
        else:
            await interaction.response.send_message("⛔ Already at the first page.", ephemeral=True)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_message(interaction)
        else:
            await interaction.response.send_message("⛔ Already at the last page.", ephemeral=True)

@tree.command(name="listriddles", description="List all submitted riddles")
@app_commands.checks.has_permissions(manage_guild=True)
async def listriddles(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not submitted_questions:
        await interaction.followup.send("📭 No riddles found in the queue.", ephemeral=True)
        return
    view = QuestionListView(interaction.user.id, submitted_questions)
    await interaction.followup.send(content=view.get_page_content(), view=view, ephemeral=True)

@tree.command(name="removeriddle", description="Remove a submitted riddle by ID")
@app_commands.checks.has_permissions(manage_guild=True)
async def removeriddle(interaction: discord.Interaction):
    class RemoveRiddleModal(discord.ui.Modal, title="Remove a Riddle"):
        question_id = discord.ui.TextInput(
            label="Enter the ID of the riddle to remove",
            placeholder="e.g. 3",
            required=True,
            max_length=10
        )

        async def on_submit(self, modal_interaction: discord.Interaction):
            qid = self.question_id.value.strip()
            idx = next((i for i, q in enumerate(submitted_questions) if str(q.get("id")) == qid), None)
            if idx is None:
                await modal_interaction.response.send_message(f"⚠️ No riddle found with ID `{qid}`.", ephemeral=True)
                return
            removed = submitted_questions.pop(idx)
            save_json(QUESTIONS_FILE, submitted_questions)
            await modal_interaction.response.send_message(f"✅ Removed riddle ID {qid}: \"{removed['question']}\"", ephemeral=True)

    await interaction.response.send_modal(RemoveRiddleModal())


# --- Submit riddle modal ---
import traceback  # at the top of your file

class SubmitRiddleModal(discord.ui.Modal, title="Submit a New Riddle"):
    question = discord.ui.TextInput(
        label="Riddle Question",
        style=discord.TextStyle.paragraph,
        placeholder="Enter your riddle question here",
        required=True,
        max_length=1000
    )
    answer = discord.ui.TextInput(
        label="Answer",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the answer here",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            global max_id
            q = self.question.value.strip().replace("\n", " ").replace("\r", " ")
            a = self.answer.value.strip()
            q_normalized = q.lower().replace(" ", "")
            for existing in submitted_questions:
                existing_q = existing["question"].strip().lower().replace(" ", "")
                if existing_q == q_normalized:
                    await interaction.response.send_message(
                        "⚠️ This riddle has already been submitted. Please try a different one.", 
                        ephemeral=True
                    )
                    return

            new_id = get_next_id()
            uid = str(interaction.user.id)
            submitted_questions.append({
                "id": new_id,
                "question": q,
                "answer": a,
                "submitter_id": uid
            })
            save_json(QUESTIONS_FILE, submitted_questions)

            # Notify admins and moderators with Manage Messages permission
            if NOTIFY_USER_ID:
                try:
                    notify_user = await client.fetch_user(int(NOTIFY_USER_ID))
                    dm = await notify_user.create_dm()
                    submitter_name = interaction.user.display_name
                    await dm.send(
                        f"🧠 @{submitter_name} has submitted a new Riddle of the Day. "
                        "Use `/listriddles` to view the question and `/removeriddle` if moderation is needed."
                    )
                except Exception as e:
                    print(f"Failed to notify user {NOTIFY_USER_ID}: {e}")
            else:
                print("NOTIFY_USER_ID environment variable not set.")

            # Award point to submitter only once per day
            today = date.today()
            last_award_date = submission_dates.get(uid)
            awarded_point_msg = ""
            if last_award_date != today:
                scores[uid] = scores.get(uid, 0) + 1
                save_json(SCORES_FILE, scores)
                submission_dates[uid] = today
                awarded_point_msg = (
                    "\n🏅 You’ve been awarded 1 point for your submission, and you will _not_ lose your streak when your riddle is posted! "
                    "You're welcome to submit more riddles today, but keep in mind: you can only earn 1 submission point per day. Submit another tomorrow to earn an additional point!"
                )

            try:
                dm = await interaction.user.create_dm()
                await dm.send(
                    "✅ Thanks for submitting a riddle! It is now in the queue.\n"
                    "⚠️ You will **not** be able to answer your own riddle when it is posted."
                    + awarded_point_msg
                )
            except discord.Forbidden:
                pass

            await interaction.response.send_message(
                "✅ Your riddle has been submitted and added to the queue! Check your DMs.", ephemeral=True
            )
        except Exception as e:
            print("Error in on_submit:", e)
            traceback.print_exc()
            await interaction.response.send_message(
                "⚠️ Something went wrong. Try again.", ephemeral=True
            )



@tree.command(name="submitriddle", description="Submit a new riddle via a form")
async def submitriddle(interaction: discord.Interaction):
    await interaction.response.send_modal(SubmitRiddleModal())


@tree.command(name="addpoints", description="Add 1 point to a user's score")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(user="The user to award a point to")
async def addpoints(interaction: discord.Interaction, user: discord.User):
    uid = str(user.id)
    scores[uid] = scores.get(uid, 0) + 1
    streaks[uid] = streaks.get(uid, 0) + 1
    save_all_scores()
    await interaction.response.send_message(
        f"✅ Added 1 point and 1 streak to {user.mention}. New score: {scores[uid]}, new streak: {streaks[uid]}",
        ephemeral=True
    )

@tree.command(name="removepoint", description="Remove 1 point from a user's score")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(user="The user to remove a point from")
async def removepoint(interaction: discord.Interaction, user: discord.User):
    uid = str(user.id)
    scores[uid] = max(0, scores.get(uid, 0) - 1)
    streaks[uid] = 0
    save_all_scores()
    await interaction.response.send_message(
        f"❌ Removed 1 point and reset streak for {user.mention}. New score: {scores[uid]}, streak reset to 0.",
        ephemeral=True
    )

@tree.command(name="score", description="View your score and rank")
async def score(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    sv = scores.get(uid, 0)
    st = streaks.get(uid, 0)
    await interaction.response.send_message(
        f"📊 {interaction.user.display_name}'s score: **{sv}**, 🔥 Streak: {st}\n🏅 {get_rank(sv, st)}",
        ephemeral=False
    )


# --- Updated /leaderboard command with pagination ---
class LeaderboardView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.current_page = 0
        self.sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self.total_pages = max((len(self.sorted_scores) - 1) // 10 + 1, 1)

    async def format_page(self):
        start = self.current_page * 10
        end = start + 10
        embed = discord.Embed(
            title=f"🏆 Riddle Leaderboard ({self.current_page + 1}/{self.total_pages})",
            color=discord.Color.gold()
        )
        for i, (uid, sv) in enumerate(self.sorted_scores[start:end], start=start + 1):
            try:
                user = client.get_user(int(uid)) or await client.fetch_user(int(uid))
                name = user.display_name
            except:
                name = "Unknown"
            st = streaks.get(uid, 0)
            embed.add_field(name=f"{i}. {name}", value=f"Score: {sv} | 🔥 Streak: {st}\n🏅Rank: {get_rank(sv, st)}", inline=False)
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This leaderboard isn't for you.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            embed = await self.format_page()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("⛔ Already at the first page.", ephemeral=True)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ This leaderboard isn't for you.", ephemeral=True)
            return
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            embed = await self.format_page()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("⛔ Already at the last page.", ephemeral=True)


@tree.command(name="leaderboard", description="Show the top solvers")
async def leaderboard(interaction: discord.Interaction):
    if not scores:
        await interaction.response.send_message("📭 No scores available yet.", ephemeral=False)
        return
    view = LeaderboardView(interaction.user.id)
    embed = await view.format_page()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


# --- Rest of your code unchanged ---


@client.event
async def on_message(message):
    if message.author.bot:
        return

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    if message.channel.id != ch_id:
        return

    global correct_users, guess_attempts, deducted_for_user, current_riddle

    user_id = str(message.author.id)
    content = message.content.strip()

    if not current_riddle or current_answer_revealed:
        return

    if current_riddle.get("submitter_id") == user_id:
        try: await message.delete()
        except: pass
        await message.channel.send(f"⛔ You submitted this riddle and cannot answer it, {message.author.mention}.", delete_after=10)
        return

    if user_id in correct_users:
        try: await message.delete()
        except: pass
        await message.channel.send(f"✅ You already answered correctly, {message.author.mention}. No more guesses counted.", delete_after=5)
        return

    attempts = guess_attempts.get(user_id, 0)
    if attempts >= 5:
        try: await message.delete()
        except: pass
        await message.channel.send(f"❌ You are out of guesses for this riddle, {message.author.mention}.", delete_after=5)
        return

    guess_attempts[user_id] = attempts + 1

    # *** This part must be indented inside on_message ***
    user_words = clean_and_filter(content)
    answer_words = clean_and_filter(current_riddle["answer"])

    if any(word in user_words for word in answer_words):
        correct_users.add(user_id)
        scores[user_id] = scores.get(user_id, 0) + 1
        streaks[user_id] = streaks.get(user_id, 0) + 1
        save_all_scores()
        try: await message.delete()
        except: pass
        await message.channel.send(f"🎉 Correct, {message.author.mention}! Your total score: {scores[user_id]}")
    else:
        remaining = 5 - guess_attempts[user_id]
        if remaining == 0 and user_id not in deducted_for_user:
            scores[user_id] = max(0, scores.get(user_id, 0) - 1)
            streaks[user_id] = 0
            deducted_for_user.add(user_id)
            save_all_scores()
            await message.channel.send(f"❌ Incorrect, {message.author.mention}. You've used all guesses and lost 1 point.", delete_after=8)
        elif remaining > 0:
            await message.channel.send(f"❌ Incorrect, {message.author.mention}. {remaining} guess(es) left.", delete_after=6)
        try: await message.delete()
        except: pass

    # Countdown to answer reveal
    now_utc = datetime.now(timezone.utc)
    reveal_dt = datetime.combine(now_utc.date(), time(23, 0), tzinfo=timezone.utc)
    if now_utc >= reveal_dt:
        reveal_dt += timedelta(days=1)
    delta = reveal_dt - now_utc
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    countdown_msg = f"⏳ Answer will be revealed in {hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}."
    await message.channel.send(countdown_msg, delete_after=12)


# --- Scheduled tasks ---

@tasks.loop(time=time(18, 55, tzinfo=timezone.utc))
async def daily_purge():
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if not channel:
        print("Channel not found for daily purge.")
        return
    try:
        async for msg in channel.history(limit=100):
            await msg.delete()
        print("Daily purge completed.")
    except Exception as e:
        print(f"Error during daily purge: {e}")

@tasks.loop(time=time(18, 57, tzinfo=timezone.utc))
async def notify_upcoming_riddle():
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if channel:
        await channel.send("⏳ The next riddle will be posted soon! Submit your own riddle by using the /submitriddle command")

@tasks.loop(time=time(19, 0, tzinfo=timezone.utc))
async def post_riddle():
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user, submitted_questions

    # Reload questions fresh from file each time a riddle posts
    submitted_questions = load_json(QUESTIONS_FILE)

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if not channel:
        print("Channel not found for posting riddle.")
        return

    current_riddle = pick_next_riddle()
    current_answer_revealed = False
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()

    base_text = format_question_text(current_riddle)

    base_text = format_question_text(current_riddle)

    # Append submitter mention or default text
    submitter_id = current_riddle.get("submitter_id")
    if submitter_id is None:
        submitter_text = "\n_(Riddle submitted by **Riddle of the Day Bot**)_"
    else:
        try:
            user = await client.fetch_user(int(submitter_id))
            submitter_text = f"\n_(Riddle submitted by {user.mention})_"
        except Exception as e:
            print(f"Could not fetch submitter for riddle {current_riddle['id']}: {e}")
            submitter_text = "\n_(Riddle submitted by **Riddle of the Day Bot**)_"

    final_text = base_text + submitter_text
    await channel.send(final_text)

from datetime import time, timezone

@tasks.loop(time=time(23, 0, tzinfo=timezone.utc))
async def reveal_answer():
    global current_answer_revealed

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)

    if not channel:
        print("❌ Channel not found in reveal_answer()")
        return
    if current_riddle is None:
        print("❌ No current_riddle in reveal_answer()")
        return

    print(f"✅ Revealing answer for riddle {current_riddle['id']}")
    answer_text = (
        f"🔔 **Answer to riddle {current_riddle['id']}:** {current_riddle['answer']}\n\n 💡 Use the `/submitriddle` command to submit your own riddle!"
    )
    await channel.send(answer_text)

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
            except Exception as e:
                print(f"Could not fetch user {user_id_str}: {e}")

        await channel.send("🎉 Congratulations to:\n" + "\n".join(congrats_lines))

    current_answer_revealed = True


@tasks.loop(time=time(23, 1, tzinfo=timezone.utc))
async def post_no_one_guessed_message():
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if not channel:
        print("❌ Channel not found in post_no_one_guessed_message()")
        return

    if not correct_users:
        print("ℹ️ No correct users — posting 'no one guessed it' message after answer reveal.")
        await channel.send("😢 No one guessed the riddle correctly today.")
    else:
        print(f"🎯 {len(correct_users)} user(s) got it right — no 'no one guessed' message needed.")


# --- /riddleofthedaycommands command ---
@tree.command(name="riddleofthedaycommands", description="List all available Riddle of the Day commands")
async def riddleofthedaycommands(interaction: discord.Interaction):
    commands_list = """
**Available Riddle of the Day Commands:**

• `/riddleofthedaycommands` - Show this list of commands.
• `/submitriddle` - Submit a new riddle via a form.
• `/score` - View your current score and rank.
• `/leaderboard` - Show the top solvers.
• `/ranks` - Show the rank descriptions.

ADMIN ONLY COMMANDS
• `/listriddles` - List all submitted riddles.
• `/removeriddle` - Remove a riddle by ID.
• `/addpoints` - Add a point to a user.
• `/removepoint` - Remove a point from a user.


"""
    await interaction.response.send_message(commands_list, ephemeral=True)


# --- /ranks command ---
@tree.command(name="ranks", description="Show rank descriptions")
async def ranks(interaction: discord.Interaction):
    ranks_description = """
**🏅 Riddle of the Day Ranks**

🍣 **Master Sushi Chef**  
Awarded to the user(s) with the highest score.

🔥 **Streak-Based Titles** (based on consecutive correct riddles):
• 🔥 **Streak Samurai** — 3-day streak  
• 🍤 **Tempura Titan** — 5-day streak  
• 🍣 **Nigiri Ninja** — 10-day streak  
• 🥢 **Rollmaster Ronin** — 20-day streak  
• 💚🔥 **Wasabi Warlord** — 30+ day streak

🎯 **Score-Based Ranks**:
• 🍽️ **Sushi Newbie** — 0 to 5 points  
• 🍣 **Maki Novice** — 6 to 15 points  
• 🍤 **Sashimi Skilled** — 16 to 25 points  
• 🧠 **Brainy Botan** — 26 to 50 points  
• 🧪 **Sushi Einstein** — 51+ points
"""
    await interaction.response.send_message(ranks_description, ephemeral=True)


# --- On Ready ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    await tree.sync()

    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if not channel:
        print("❌ Could not find riddle channel.")
        return

    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user
    
    # Start the normal scheduled tasks as usual
    daily_purge.start()
    notify_upcoming_riddle.start()
    post_riddle.start()
    reveal_answer.start()
    post_no_one_guessed_message.start()
    
   


# --- Run bot ---
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not DISCORD_TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN environment variable not set.")
else:
    client.run(DISCORD_TOKEN)
