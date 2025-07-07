@tree.command(name="run_test_sequence", description="Run a full test riddle workflow")
@app_commands.checks.has_permissions(administrator=True)
async def run_test_sequence(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(channel_id)
    if not channel:
        await interaction.followup.send("❌ Test failed: Channel not found.", ephemeral=True)
        return

    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    # Define a test riddle
    current_riddle = {
        "id": 9999,
        "question": "What has keys but can't open locks?",
        "answer": "piano",
        "submitter_id": None,
    }
    current_answer_revealed = False
    correct_users = set()
    guess_attempts = {}
    deducted_for_user = set()

    # Post the riddle embed
    embed = discord.Embed(
        title=f"🧩 Riddle of the Day #{current_riddle['id']}",
        description=f"**Riddle:** {current_riddle['question']}\n\n_(Riddle submitted by **Riddle of the Day Bot**)_",
        color=discord.Color.blurple()
    )
    await channel.send(embed=embed)

    await interaction.followup.send("✅ Test riddle posted. Waiting 30 seconds before revealing answer...", ephemeral=True)

    # Wait 30 seconds to simulate answering period
    await asyncio.sleep(30)

    # Reveal the answer
    answer_embed = discord.Embed(
        title=f"🔔 Answer to Riddle #{current_riddle['id']}",
        description=f"**Answer:** {current_riddle['answer']}\n\n💡 Use `/submitriddle` to submit your own riddle!",
        color=discord.Color.green()
    )
    await channel.send(embed=answer_embed)

    # Post congratulations or no guesses message
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

    # Mark answer as revealed and clear state for next test
    current_answer_revealed = True
    correct_users.clear()
    guess_attempts.clear()
    deducted_for_user.clear()
    current_riddle = None

    await channel.send("✅ Test sequence completed. You can run `/run_test_sequence` again to test.")
