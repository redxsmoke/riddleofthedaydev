import discord
from discord import app_commands, Embed, Interaction
from discord.ui import View, Button
import os
import asyncio


db_pool = None

def set_db_pool(pool):
    global db_pool
    db_pool = pool

 
# You need to create your client first
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Assume you have imported your DB helper functions somewhere:
# from db import get_user, upsert_user, insert_submitted_question, db_pool

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

# -------------------
# Your commands below
# -------------------
def setup(tree: app_commands.CommandTree, client: discord.Client):
    # All command definitions go below inside setup()


    @tree.command(name="myranks", description="Show your riddle score, streak, and rank")
    async def myranks(interaction: discord.Interaction):
        print("[myranks] Command invoked")

        if db_pool is None:
            print("[myranks] ERROR: db_pool is None (DB not initialized)")
            await interaction.response.send_message("Database connection not initialized.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        print("[myranks] Deferred interaction response")

        uid = interaction.user.id
        print(f"[myranks] Fetching user with id: {uid}")

        try:
            row = await get_user(uid)
            print(f"[myranks] DB query result: {row}")
        except Exception as e:
            print(f"[myranks] ERROR querying DB: {e}")
            await interaction.followup.send("❌ Database query failed.", ephemeral=True)
            return

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

        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
            print("[myranks] Embed sent successfully")
        except Exception as e:
            print(f"[myranks] ERROR sending embed: {e}")


    @tree.command(name="submitriddle", description="Submit a new riddle for the daily contest")
    @app_commands.describe(question="The riddle question", answer="The answer to the riddle")
    async def submitriddle(interaction: discord.Interaction, question: str, answer: str):
        question = question.strip()
        answer = answer.strip().lower()

        if not question or not answer:
            await interaction.response.send_message("❌ Question and answer cannot be empty.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)  # Defer early

        # Check for duplicate question in DB (case-insensitive)
        async with db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM user_submitted_questions WHERE LOWER(TRIM(question)) = LOWER(TRIM($1))",
                question
            )
        if existing:
            await interaction.followup.send(
                "❌ This riddle has already been submitted. Please try a different one.",
                ephemeral=True
            )
            return

        # Insert into DB
        await insert_submitted_question(user_id=interaction.user.id, question=question, answer=answer)

        # Update user score by 1
        await update_user_score_and_streak(interaction.user.id, add_score=1)

        embed = Embed(
            title="🧩 Riddle Submitted!",
            description=f"**Riddle:** {question}\n\n_(Submitted by {interaction.user.display_name})_",
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed)

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


    @tree.command(name="addpoints", description="Add points to a user")
    @app_commands.describe(user="The user to add points to", amount="Number of points to add (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addpoints(interaction: discord.Interaction, user: discord.User, amount: int):
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        new_score, _ = await update_user_score_and_streak(user.id, add_score=amount)

        await interaction.followup.send(
            f"✅ Added {amount} point(s) to {user.mention}. New score: {new_score}",
            ephemeral=True
        )


    @tree.command(name="addstreak", description="Add streak days to a user")
    @app_commands.describe(user="The user to add streak days to", amount="Number of streak days to add (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addstreak(interaction: discord.Interaction, user: discord.User, amount: int):
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        _, new_streak = await update_user_score_and_streak(user.id, add_streak=amount)

        await interaction.followup.send(
            f"✅ Added {amount} streak day(s) to {user.mention}. New streak: {new_streak}",
            ephemeral=True
        )


    @tree.command(name="removepoints", description="Remove points from a user")
    @app_commands.describe(user="The user to remove points from", amount="Number of points to remove (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removepoints(interaction: discord.Interaction, user: discord.User, amount: int):
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        new_score, _ = await update_user_score_and_streak(user.id, add_score=-amount)

        await interaction.followup.send(
            f"❌ Removed {amount} point(s) from {user.mention}. New score: {new_score}",
            ephemeral=True
        )


    @tree.command(name="removestreak", description="Remove streak days from a user")
    @app_commands.describe(user="The user to remove streak days from", amount="Number of streak days to remove (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removestreak(interaction: discord.Interaction, user: discord.User, amount: int):
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        _, new_streak = await update_user_score_and_streak(user.id, add_streak=-amount)

        await interaction.followup.send(
            f"❌ Removed {amount} streak day(s) from {user.mention}. New streak: {new_streak}",
            ephemeral=True
        )


    @tree.command(name="ranks", description="View all rank tiers and how to earn them")
    async def ranks(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

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
        await interaction.followup.send(embed=embed, ephemeral=True)


    @tree.command(name="removeriddle", description="Remove a riddle by its number (ID)")
    @app_commands.describe(riddle_id="The ID number of the riddle to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removeriddle(interaction: discord.Interaction, riddle_id: int):
        await interaction.response.defer(ephemeral=True)
        # Remove riddle from DB instead of in-memory list
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM user_submitted_questions WHERE id = $1",
                riddle_id
            )
        if result.endswith("0"):
            await interaction.followup.send(f"❌ No riddle found with ID #{riddle_id}.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Removed riddle #{riddle_id}.", ephemeral=True)


    ITEMS_PER_PAGE = 10

    class ListRiddlesView(View):
        def __init__(self, riddles, author_id, bot):
            super().__init__(timeout=180)
            self.riddles = riddles
            self.author_id = author_id
            self.current_page = 0
            self.total_pages = max(1, (len(riddles) - 1) // ITEMS_PER_PAGE + 1)
            self.bot = bot
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
                    user = await self.bot.fetch_user(int(riddle['user_id'] or riddle['submitter_id']))
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
        await interaction.response.defer(ephemeral=True)

        async with db_pool.acquire() as conn:
            riddles = await conn.fetch("SELECT * FROM user_submitted_questions ORDER BY created_at DESC")

        if not riddles:
            await interaction.followup.send("No riddles have been submitted yet.", ephemeral=True)
            return

        view = ListRiddlesView(riddles, interaction.user.id, interaction.client)
        embed = await view.get_page_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


    @tree.command(name="leaderboard", description="Show the riddle leaderboard with pagination")
    async def leaderboard(interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

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
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


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

            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_id, score, streak FROM users WHERE user_id = ANY($1::bigint[])",
                    page_users
                )

            max_score = max((r["score"] for r in rows), default=0)

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



# A top-level helper function for updating score and streak
async def update_user_score_and_streak(user_id: int, add_score=0, add_streak=0):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT score, streak FROM users WHERE user_id=$1", user_id)
        if row:
            new_score = max(0, row["score"] + add_score)
            new_streak = max(0, row["streak"] + add_streak)
            await conn.execute(
                "UPDATE users SET score=$1, streak=$2 WHERE user_id=$3",
                new_score, new_streak, user_id
            )
        else:
            new_score = max(0, add_score)
            new_streak = max(0, add_streak)
            await conn.execute(
                "INSERT INTO users (user_id, score, streak) VALUES ($1, $2, $3)",
                user_id, new_score, new_streak
            )
    return new_score, new_streak


 


