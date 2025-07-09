from discord import app_commands, Interaction, Embed
from discord.ui import View, Button
import discord

# You should have your scores and streaks dicts somewhere accessible
# Example:
# scores = {"user_id_str": score_int, ...}
# streaks = {"user_id_str": streak_int, ...}

def get_combined_sort_key(user_id):
    return (scores.get(user_id, 0), streaks.get(user_id, 0))

class LeaderboardView(View):
    def __init__(self, client, users, per_page=10):
        super().__init__(timeout=120)  # 2 minutes timeout
        self.client = client
        self.users = users  # list of user_id strings sorted
        self.per_page = per_page
        self.current_page = 0
        self.max_page = (len(users) - 1) // per_page

        # Disable Prev on first page
        self.prev_button.disabled = True
        if self.max_page == 0:
            self.next_button.disabled = True

    async def update_message(self, interaction: Interaction):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_users = self.users[start:end]

        embed = Embed(
            title=f"🏆 Riddle Leaderboard (Page {self.current_page + 1} / {self.max_page + 1})",
            color=discord.Color.gold()
        )

        description_lines = []
        max_score = max((scores.get(u, 0) for u in self.users), default=0)

        for idx, user_id_str in enumerate(page_users, start=start + 1):
            try:
                user = await self.client.fetch_user(int(user_id_str))
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

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1

        # Enable/disable buttons accordingly
        button.disabled = self.current_page == 0
        self.next_button.disabled = False
        await self.update_message(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: Interaction, button: Button):
        if self.current_page < self.max_page:
            self.current_page += 1

        # Enable/disable buttons accordingly
        button.disabled = self.current_page == self.max_page
        self.prev_button.disabled = False
        await self.update_message(interaction)

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
