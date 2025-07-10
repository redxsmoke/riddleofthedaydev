import discord
from discord import app_commands, Embed, Interaction
from discord.ui import View, Button
import os
import asyncio
import traceback
from db import get_user, insert_submitted_question  # import from db, NOT db_pool

# THIS is crucial: store your own copy of db_pool here and allow it to be set
db_pool = None

def set_db_pool(pool):
    global db_pool
    db_pool = pool



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


    # Helper function to ensure user exists in DB
    async def ensure_user_exists(user_id: int):
        if db_pool is None:
            print("[ensure_user_exists] ERROR: db_pool is None")
            return
        async with db_pool.acquire() as conn:
            # Try insert, ignore if already exists
            try:
                await conn.execute(
                    """
                    INSERT INTO users (user_id, score, streak, created_at)
                    VALUES ($1, 0, 0, CURRENT_TIMESTAMP )
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    user_id
                )
                print(f"[ensure_user_exists] Ensured user {user_id} exists")
            except Exception as e:
                print(f"[ensure_user_exists] ERROR inserting user {user_id}: {e}")


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
        print(f"[myranks] Ensuring user {uid} exists in DB")
        await ensure_user_exists(uid)

        print(f"[myranks] Fetching user with id: {uid}")
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT score, streak FROM users WHERE user_id = $1", uid)
            print(f"[myranks] DB query result: {row}")
        except Exception as e:
            print(f"[myranks] ERROR querying DB: {e}")
            import traceback
            traceback.print_exc()
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
        print("[submitriddle] Command invoked")
        question = question.strip()
        answer = answer.strip().lower()
        print(f"[submitriddle] Received question: '{question}' and answer: '{answer}'")

        if not question or not answer:
            print("[submitriddle] Question or answer is empty")
            await interaction.response.send_message("❌ Question and answer cannot be empty.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)  # Defer early
        print("[submitriddle] Deferred interaction response")

        uid = interaction.user.id
        print(f"[submitriddle] Ensuring user {uid} exists in DB")

        try:
            async with db_pool.acquire() as conn:
                # Insert user if not exists
                await conn.execute("""
                    INSERT INTO users (user_id, score, streak, created_at)
                    VALUES ($1, 0, 0, NOW())
                    ON CONFLICT (user_id) DO NOTHING
                """, uid)

                existing = await conn.fetchrow(
                    "SELECT * FROM user_submitted_questions WHERE LOWER(TRIM(question)) = LOWER(TRIM($1))",
                    question
                )
            print(f"[submitriddle] Duplicate check result: {existing}")
        except Exception as e:
            print(f"[submitriddle] ERROR checking for duplicate question: {e}")
            await interaction.followup.send("❌ Database error during duplicate check.", ephemeral=True)
            return

        if existing:
            print("[submitriddle] Duplicate riddle found, aborting submission")
            await interaction.followup.send(
                "❌ This riddle has already been submitted. Please try a different one.",
                ephemeral=True
            )
            return

        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_submitted_questions (user_id, question, answer, created_at)
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                    """,
                    uid, question, answer
                )
            print("[submitriddle] Inserted submitted question")
        except Exception as e:
            print(f"[submitriddle] ERROR inserting submitted question: {e}")
            await interaction.followup.send("❌ Failed to submit your riddle.", ephemeral=True)
            return

        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE users SET score = score + 1 WHERE user_id = $1
                    """, uid
                )
            print("[submitriddle] Updated user score by 1")
        except Exception as e:
            print(f"[submitriddle] ERROR updating user score: {e}")
            # Not critical enough to block response, continue anyway

        # Optional: Notify mod user
        notify_user_id = os.getenv("NOTIFY_USER_ID")
        if notify_user_id:
            try:
                notify_user = await client.fetch_user(int(notify_user_id))
                if notify_user:
                    await notify_user.send(
                        f"@{interaction.user.display_name} submitted a new riddle. Use `/listriddles` to view and `/removeriddle` to moderate."
                    )
                print("[submitriddle] Notified mod user")
            except Exception as e:
                print(f"[submitriddle] Failed to send DM to notify user: {e}")

        # Optional: DM submitter confirmation
        dm_message = (
            "✅ Thank you for submitting your riddle! It has been added to the queue.\n\n"
            "📌 On the day your riddle posts, you won’t be able to answer it yourself.\n"
            "🎉 Your score has already been increased by 1, keep up the great work!"
        )
        try:
            await interaction.user.send(dm_message)
            print("[submitriddle] DM confirmation sent to submitter")
        except Exception:
            print("[submitriddle] Failed to send DM confirmation to submitter")

        await interaction.followup.send(
            "✅ Your riddle was submitted successfully! Check your DMs for more info.",
            ephemeral=True
)


    @tree.command(name="addpoints", description="Add points to a user")
    @app_commands.describe(user="The user to add points to", amount="Number of points to add (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addpoints(interaction: discord.Interaction, user: discord.User, amount: int):
        print("[addpoints] Command invoked")
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        new_score, _ = await update_user_score_and_streak(user.id, add_score=amount)
        print(f"[addpoints] Added {amount} points to user {user.id}, new score: {new_score}")

        await interaction.followup.send(
            f"✅ Added {amount} point(s) to {user.mention}. New score: {new_score}",
            ephemeral=True
        )



    @tree.command(name="addstreak", description="Add streak days to a user")
    @app_commands.describe(user="The user to add streak days to", amount="Number of streak days to add (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addstreak(interaction: discord.Interaction, user: discord.User, amount: int):
        print("[addstreak] Command invoked")
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        _, new_streak = await update_user_score_and_streak(user.id, add_streak=amount)
        print(f"[addstreak] Added {amount} streak days to user {user.id}, new streak: {new_streak}")

        await interaction.followup.send(
            f"✅ Added {amount} streak day(s) to {user.mention}. New streak: {new_streak}",
            ephemeral=True
        )



    @tree.command(name="removepoints", description="Remove points from a user")
    @app_commands.describe(user="The user to remove points from", amount="Number of points to remove (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removepoints(interaction: discord.Interaction, user: discord.User, amount: int):
        print("[removepoints] Command invoked")
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        new_score, _ = await update_user_score_and_streak(user.id, add_score=-amount)
        print(f"[removepoints] Removed {amount} points from user {user.id}, new score: {new_score}")

        await interaction.followup.send(
            f"❌ Removed {amount} point(s) from {user.mention}. New score: {new_score}",
            ephemeral=True
        )



    @tree.command(name="removestreak", description="Remove streak days from a user")
    @app_commands.describe(user="The user to remove streak days from", amount="Number of streak days to remove (positive integer)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removestreak(interaction: discord.Interaction, user: discord.User, amount: int):
        print("[removestreak] Command invoked")
        await interaction.response.defer(ephemeral=True)

        if amount <= 0:
            await interaction.followup.send("❌ Amount must be a positive integer.", ephemeral=True)
            return

        _, new_streak = await update_user_score_and_streak(user.id, add_streak=-amount)
        print(f"[removestreak] Removed {amount} streak days from user {user.id}, new streak: {new_streak}")

        await interaction.followup.send(
            f"❌ Removed {amount} streak day(s) from {user.mention}. New streak: {new_streak}",
            ephemeral=True
        )

    @tree.command(name="ranks", description="View all rank tiers and how to earn them")
    async def ranks(interaction: discord.Interaction):
        print("[ranks] Command invoked")
        await interaction.response.defer(ephemeral=True)
        print("[ranks] Deferred interaction response")

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
        print("[ranks] Embed sent")



    @tree.command(name="removeriddle", description="Remove a riddle by its number (ID)")
    @app_commands.describe(riddle_id="The ID number of the riddle to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removeriddle(interaction: discord.Interaction, riddle_id: int):
        print(f"[removeriddle] Command invoked with riddle_id={riddle_id}")
        await interaction.response.defer(ephemeral=True)

        try:
            async with db_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM user_submitted_questions WHERE riddle_id = $1",
                    riddle_id
                )
            print(f"[removeriddle] DB execute result: {result}")

            if result.endswith("0"):
                await interaction.followup.send(f"❌ No riddle found with ID #{riddle_id}.", ephemeral=True)
                print(f"[removeriddle] No riddle found with ID #{riddle_id}")
            else:
                await interaction.followup.send(f"✅ Removed riddle #{riddle_id}.", ephemeral=True)
                print(f"[removeriddle] Removed riddle #{riddle_id}")
        except Exception as e:
            print(f"[removeriddle] ERROR: {e}")
            await interaction.followup.send("❌ An error occurred while removing the riddle.", ephemeral=True)



    @tree.command(name="listriddles", description="List all submitted riddles with pagination")
    async def listriddles(interaction: discord.Interaction):
        print("[listriddles] Command invoked")
        await interaction.response.defer(ephemeral=True)

        async with db_pool.acquire() as conn:
            riddles = await conn.fetch("SELECT * FROM user_submitted_questions ORDER BY created_at DESC")
        print(f"[listriddles] Fetched {len(riddles)} riddles")

        if not riddles:
            await interaction.followup.send("No riddles have been submitted yet.", ephemeral=True)
            print("[listriddles] No riddles found")
            return

        try:
            view = ListRiddlesView(riddles, interaction.user.id, interaction.client)
            embed = await view.get_page_embed()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            print("[listriddles] Sent riddles list embed")
        except Exception as e:
            print(f"[listriddles] ERROR generating or sending embed: {e}")
            await interaction.followup.send("❌ Failed to show riddles.", ephemeral=True)


    @tree.command(name="leaderboard", description="Show the riddle leaderboard with pagination")
    async def leaderboard(interaction: Interaction):
        print("[leaderboard] Command invoked")
        await interaction.response.defer(ephemeral=True)

        try:
            uid = interaction.user.id
            print(f"[submitted riddle] Ensuring user {uid} exists in DB")
            await ensure_user_exists(uid)

            async with db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT user_id, score, streak FROM users WHERE score >= 1 OR streak >= 1")
            print(f"[leaderboard] Fetched {len(rows)} users")

            filtered_users = [row["user_id"] for row in rows]
            if not filtered_users:
                await interaction.followup.send("No leaderboard data available.", ephemeral=True)
                print("[leaderboard] No leaderboard data available")
                return

            rows.sort(key=lambda r: (r["score"], r["streak"]), reverse=True)

            view = LeaderboardView(client, filtered_users, per_page=10)
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
            print("[leaderboard] Leaderboard embed sent")

        except Exception as e:
            print(f"[leaderboard] ERROR: {e}")
            try:
                await interaction.followup.send("❌ An error occurred while fetching the leaderboard.", ephemeral=True)
            except Exception:
                pass



    @tree.command(name="purge", description="Delete all messages in this channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def purge(interaction: discord.Interaction):
        print("[purge] Command invoked")
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ This command can only be used in text channels.", ephemeral=True)
            print("[purge] Command used outside text channel")
            return

        await interaction.response.defer(ephemeral=True)
        print("[purge] Deferred interaction response")

        def is_not_pinned(m):
            return not m.pinned

        deleted = await channel.purge(limit=None, check=is_not_pinned)
        await interaction.followup.send(f"🧹 Purged {len(deleted)} messages.", ephemeral=True)
        print(f"[purge] Purged {len(deleted)} messages")




from discord import app_commands, Interaction
import random
import os
from your_main_file import current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user
from your_main_file import get_unused_questions, format_question_embed, client  # import as needed

@tree.command(name="testriddle", description="Post a random riddle once for testing")
async def test_riddle(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)

    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    if current_riddle is not None:
        await interaction.followup.send("⛔ There is already an active riddle.", ephemeral=True)
        return

    riddles = await get_unused_questions()
    if not riddles:
        await interaction.followup.send("⚠️ No riddles available to post.", ephemeral=True)
        return

    riddle = random.choice(riddles)
    current_riddle = riddle
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    submitter = None
    if riddle.get("user_id"):
        submitter = client.get_user(int(riddle["user_id"]))

    embed = await format_question_embed(riddle, submitter)

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        await interaction.followup.send("❌ Riddle channel not found.", ephemeral=True)
        return

    await channel.send(embed=embed)
    await interaction.followup.send(f"✅ Riddle #{riddle['riddle_id']} posted in {channel.mention}.", ephemeral=True)









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

async def ensure_user_exists(user_id: int):
    async with db_pool.acquire() as conn:
        # Check if user exists
        row = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if not row:
            # Insert new user with default score and streak
            await conn.execute(
                "INSERT INTO users (user_id, score, streak) VALUES ($1, 0, 0)",
                user_id
            )

 


