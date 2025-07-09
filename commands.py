import discord
from discord import app_commands, Embed, Interaction
from discord.ui import View, Button
import os
import asyncio

# Assume you have imported your DB helper functions somewhere:
# from db import get_user, upsert_user, insert_submitted_question

# Utility functions for ranks (unchanged)
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
        return None

tree = app_commands.CommandTree(client)
@tree.command(name="myranks", description="Show your riddle score, streak, and rank")
async def myranks(interaction: discord.Interaction):
    uid = interaction.user.id

    row = await get_user(uid)
    score_val = row["score"] if row else 0
    streak_val = row["streak"] if row else 0

    rank = get_rank(score_val)
    streak_rank = get_streak_rank(streak_val)

    embed = Embed(
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


@tree.command(name="submitriddle", description="Submit a new riddle for the daily contest")
@app_commands.describe(question="The riddle question", answer="The answer to the riddle")
async def submitriddle(interaction: discord.Interaction, question: str, answer: str):
    question = question.strip()
    answer = answer.strip().lower()

    if not question or not answer:
        await interaction.response.send_message("❌ Question and answer cannot be empty.", ephemeral=True)
        return

    # Check for duplicate question in DB (case-insensitive)
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM user_submitted_questions WHERE LOWER(TRIM(question)) = LOWER(TRIM($1))",
            question
        )
    if existing:
        await interaction.response.send_message(
            "❌ This riddle has already been submitted. Please try a different one.",
            ephemeral=True
        )
        return

    # Insert into DB
    await insert_submitted_question(user_id=interaction.user.id, question=question, answer=answer)

    embed = Embed(
        title="🧩 Riddle Submitted!",
        description=f"**Riddle:** {question}\n\n_(Submitted by {interaction.user.display_name})_",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)

    # Optional: Notify mod user
    notify_user_id = os.getenv("NOTIFY_USER_ID")
    if notify_user_id:
        try:
            notify_user = await client.fetch_user(int(notify_user_id))
            if notify_user:
                await notify_user.send(
                    f"@{interaction.user.display_name} submitted a new riddle. Use `/listriddles` to view and `/removeriddle` to moderate."
                )
        except Exception as e:
            print(f"Failed to send DM to notify user: {e}")

    # Optional: DM submitter confirmation
    dm_message = (
        "✅ Thank you for submitting your riddle! It has been added to the queue.\n\n"
        "📌 On the day your riddle posts, you won’t be able to answer it yourself.\n"
        "🎉 Your score has already been increased by 1, keep up the great work!"
    )
    try:
        await interaction.user.send(dm_message)
    except Exception:
        pass


async def update_user_score_and_streak(user_id: int, add_score=0, add_streak=0):
    row = await get_user(user_id)
    if row:
        new_score = max(0, row["score"] + add_score)
        new_streak = max(0, row["streak"] + add_streak)
    else:
        new_score = max(0, add_score)
        new_streak = max(0, add_streak)

    await upsert_user(user_id=user_id, score=new_score, streak=new_streak)
    return new_score, new_streak


@tree.command(name="addpoints", description="Add points to a user")
@app_commands.describe(user="The user to add points to", amount="Number of points to add (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def addpoints(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    new_score, _ = await update_user_score_and_streak(user.id, add_score=amount)

    await interaction.response.send_message(
        f"✅ Added {amount} point(s) to {user.mention}. New score: {new_score}",
        ephemeral=True
    )


@tree.command(name="addstreak", description="Add streak days to a user")
@app_commands.describe(user="The user to add streak days to", amount="Number of streak days to add (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def addstreak(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    _, new_streak = await update_user_score_and_streak(user.id, add_streak=amount)

    await interaction.response.send_message(
        f"✅ Added {amount} streak day(s) to {user.mention}. New streak: {new_streak}",
        ephemeral=True
    )


@tree.command(name="removepoints", description="Remove points from a user")
@app_commands.describe(user="The user to remove points from", amount="Number of points to remove (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def removepoints(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    new_score, _ = await update_user_score_and_streak(user.id, add_score=-amount)

    await interaction.response.send_message(
        f"❌ Removed {amount} point(s) from {user.mention}. New score: {new_score}",
        ephemeral=True
    )


@tree.command(name="removestreak", description="Remove streak days from a user")
@app_commands.describe(user="The user to remove streak days from", amount="Number of streak days to remove (positive integer)")
@app_commands.checks.has_permissions(manage_guild=True)
async def removestreak(interaction: discord.Interaction, user: discord.User, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be a positive integer.", ephemeral=True)
        return

    _, new_streak = await update_user_score_and_streak(user.id, add_streak=-amount)

    await interaction.response.send_message(
        f"❌ Removed {amount} streak day(s) from {user.mention}. New streak: {new_streak}",
        ephemeral=True
    )


@tree.command(name="ranks", description="View all rank tiers and how to earn them")
async def ranks(interaction: discord.Interaction):
    embed = Embed(
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


@tree.command(name="removeriddle", description="Remove a riddle by its number (ID)")
@app_commands.describe(riddle_id="The ID number of the riddle to remove")
@app_commands.checks.has_permissions(manage_guild=True)
async def removeriddle(interaction: discord.Interaction, riddle_id: int):
    # Remove riddle from DB instead of in-memory list
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_submitted_questions WHERE id = $1",
            riddle_id
        )
    if result.endswith("0"):
        await interaction.response.send_message(f"❌ No riddle found with ID #{riddle_id}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ Removed riddle #{riddle_id}.", ephemeral=True)


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
                user = await self.bot.fetch_user(int(riddle['user_id'] or riddle['submitter_id']))  # try both keys for compatibility
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
    async with db_pool.acquire() as conn:
        riddles = await conn.fetch("SELECT * FROM user_submitted_questions ORDER BY created_at DESC")

    if not riddles:
        await interaction.response.send_message("No riddles have been submitted yet.", ephemeral=True)
        return

    view = ListRiddlesView(riddles, interaction.user.id, interaction.client)
    embed = await view.get_page_embed()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@tree.command(name="leaderboard", description="Show the riddle leaderboard with pagination")
async def leaderboard(interaction: Interaction):
    await interaction.response.defer()

    # Fetch users from DB with score or streak >= 1
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, score, streak FROM users WHERE score >= 1 OR streak >= 1")

    filtered_users = [row["user_id"] for row in rows]
    if not filtered_users:
        await interaction.followup.send("No leaderboard data available.", ephemeral=True)
        return

    # Sort descending by (score, streak)
    rows.sort(key=lambda r: (r["score"], r["streak"]), reverse=True)


    view = LeaderboardView(client, filtered_users, per_page=10)

    # First page users
    initial_users = filtered_users[:10]

    embed = Embed(
        title=f"🏆 Riddle Leaderboard (Page 1 / {(len(filtered_users) - 1) // 10 + 1})",
        color=discord.Color.gold()
    )

    max_score = max((row["score"] for row in rows), default=0)

    description_lines = []
    for idx, user_id in enumerate(initial_users, start=1):
        try:
            user = await client.fetch_user(int(user_id))
            # Find user data row
            user_row = next((r for r in rows if r["user_id"] == user_id), None)
            score_val = user_row["score"] if user_row else 0
            streak_val = user_row["streak"] if user_row else 0

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
            description_lines.append(f"    • Streak: {streak_text}")
            description_lines.append(f"    • Rank: {rank}")

        except Exception:
            description_lines.append(f"#{idx} Unknown User (ID: {user_id})")

    embed.description = "\n".join(description_lines)
    await interaction.followup.send(embed=embed, view=view)


# LeaderboardView implementation with pagination buttons, similar to ListRiddlesView:
class LeaderboardView(View):
    def __init__(self, bot, users, per_page=10):
        super().__init__(timeout=180)
        self.bot = bot
        self.users = users
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = max(1, (len(users) - 1) // per_page + 1)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    async def get_page_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_users = self.users[start:end]

        embed = Embed(
            title=f"🏆 Riddle Leaderboard (Page {self.current_page + 1}/{self.total_pages})",
            color=discord.Color.gold()
        )

        # Fetch user rows for page users from DB
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, score, streak FROM users WHERE user_id = ANY($1::bigint[])",
                page_users
            )
        max_score = max((row["score"] for row in rows), default=0)

        description_lines = []
        for idx, user_id in enumerate(page_users, start=start + 1):
            try:
                user = await self.bot.fetch_user(int(user_id))
                user_row = next((r for r in rows if r["user_id"] == user_id), None)
                score_val = user_row["score"] if user_row else 0
                streak_val = user_row["streak"] if user_row else 0

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
                description_lines.append(f"    • Streak: {streak_text}")
                description_lines.append(f"    • Rank: {rank}")

            except Exception:
                description_lines.append(f"#{idx} Unknown User (ID: {user_id})")

        embed.description = "\n".join(description_lines)
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: Interaction, button: Button):
        if interaction.user.id != interaction.message.interaction.user.id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = await self.get_page_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: Interaction, button: Button):
        if interaction.user.id != interaction.message.interaction.user.id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = await self.get_page_embed()
            await interaction.response.edit_message(embed=embed, view=self)

"""
@tree.command(name="purge", description="Delete all messages in this channel")
@app_commands.checks.has_permissions(administrator=True)
async def purge(interaction: discord.Interaction):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("❌ This command can only be used in text channels.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    def is_not_pinned(m):
        return not m.pinned

    deleted = await channel.purge(limit=None, check=is_not_pinned)
    await interaction.followup.send(f"🧹 Purged {len(deleted)} messages.", ephemeral=True)
"""
"""
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

        # Announcement embed for next riddle
        announcement_embed = discord.Embed(
            title="ℹ️ Upcoming Riddle Alert!",
            description="The next riddle will be submitted soon. Get ready!\n\n💡 Submit your own riddle using the `/submitriddle` command!",
            color=discord.Color.blurple()
        )
        await channel.send(embed=announcement_embed)

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

        riddle_embed = discord.Embed(
            title=f"🧩 Riddle of the Day #{current_riddle['id']}",
            description=f"**Riddle:** {current_riddle['question']}\n\n_(Riddle submitted by **Riddle of the Day Bot**)_\n\n",
            color=discord.Color.blurple()
        )
        await channel.send(embed=riddle_embed)

        await interaction.followup.send("✅ Test riddle posted. Waiting 30 seconds before revealing answer...", ephemeral=True)

        await asyncio.sleep(30)

        answer_embed = discord.Embed(
            title=f"🔔 Answer to Riddle #{current_riddle['id']}",
            description=f"**Answer:** {current_riddle['answer']}\n\n💡 Use `/submitriddle` to submit your own riddle!",
            color=discord.Color.green()
        )
        await channel.send(embed=answer_embed)

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
        
                    # Score line (include 👑 only if top scorer)
                    score_line = f"{score_val}"
                    if score_val == max_score and max_score > 0:
                        score_line += " - 👑 🍣 Master Sushi Chef"
        
                    # Rank line
                    rank = get_rank(score_val)
        
                    # Streak rank
                    streak_rank = get_streak_rank(streak_val)
        
                    # Build lines
                    description_lines.append(f"#{idx} {user.display_name}:")
                    description_lines.append(f"    • Score: {score_line}")
                    description_lines.append(f"    • Rank: {rank}")
        
                    streak_text = f"🔥{streak_val}"
                    if streak_rank:
                        streak_text += f" - {streak_rank}"
                    description_lines.append(f"    • Streak: {streak_text}")
                    description_lines.append("")
        
                except Exception:
                    # Fallback if user fetch fails: show mention with stats
                    score_val = scores.get(user_id_str, 0)
                    rank = get_rank(score_val)
                    streak_val = streaks.get(user_id_str, 0)
                    streak_rank = get_streak_rank(streak_val)
                    streak_text = f"🔥{streak_val}"
                    if streak_rank:
                        streak_text += f" - {streak_rank}"
        
                    description_lines.append(f"#{idx} <@{user_id_str}>")
                    description_lines.append(f"    • Score: {score_val}")
                    description_lines.append(f"    • Rank: {rank}")
                    description_lines.append(f"    • Streak: {streak_text}")
                    description_lines.append("")
        
            congrats_embed.description = "\n".join(description_lines)
            await channel.send(embed=congrats_embed)
        else:
            await channel.send("😢 No one guessed the riddle correctly today.")



        
        current_answer_revealed = True
        correct_users.clear()
        guess_attempts.clear()
        deducted_for_user.clear()
        current_riddle = None
        
        await channel.send("✅ Test sequence completed. You can run `/run_test_sequence` again to test.")

setup_test_sequence_commands(tree, client)
"""