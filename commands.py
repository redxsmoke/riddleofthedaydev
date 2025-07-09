@tree.command(name="submitriddle", description="Submit a new riddle for the daily contest")
@app_commands.describe(question="The riddle question", answer="The answer to the riddle")
async def submitriddle(interaction: discord.Interaction, question: str, answer: str):
    global current_riddle, current_answer_revealed, correct_users, guess_attempts, deducted_for_user

    question = question.strip()
    answer = answer.strip().lower()

    if not question or not answer:
        await interaction.response.send_message("❌ Question and answer cannot be empty.", ephemeral=True)
        return

    # Check for duplicate question (case-insensitive, ignoring extra spaces)
    normalized_question = " ".join(question.lower().split())
    for q in submitted_questions:
        existing_question = q.get("question", "")
        normalized_existing = " ".join(existing_question.lower().split())
        if normalized_question == normalized_existing:
            await interaction.response.send_message(
                "❌ This riddle has already been submitted. Please try a different one.",
                ephemeral=True
            )
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

    # Notify moderation user
    notify_user_id = os.getenv("NOTIFY_USER_ID")
    if notify_user_id:
        try:
            notify_user = await client.fetch_user(int(notify_user_id))
            if notify_user:
                await notify_user.send(
                    f"@{interaction.user.display_name} has submitted a new riddle. "
                    "Use `/listriddles` to view the riddle and `/removeriddle` if moderation is needed."
                )
        except Exception as e:
            print(f"Failed to send DM to notify user: {e}")

    # DM the submitter with confirmation and info
    dm_message = (
        "✅ Thank you for submitting your riddle! It has been added to the queue.\n\n"
        "📌 Please note that on the day your riddle is posted, you won’t be able to answer it yourself.\n"
        "🎉 Your score has already been increased by 1, and your streak will remain intact. Keep up the great work!"
    )
    try:
        await interaction.user.send(dm_message)
    except Exception:
        pass
