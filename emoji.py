import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Your bot token from @BotFather
TOKEN = "YOUR_BOT_TOKEN"

# Directory to save animated emojis
ANIMATED_DIR = "custom_animated_emojis"
os.makedirs(ANIMATED_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "Welcome! Send me messages with animated custom emojis, and I'll save them in TGS format.\n"
        "Note: I only save animated custom emojis from accessible sticker sets.\n"
        "Static custom emojis will be ignored.\n"
        "Use /list to see saved animated emojis."
    )

async def list_emojis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all saved animated emojis"""
    animated_files = os.listdir(ANIMATED_DIR)
    
    if not animated_files:
        await update.message.reply_text("No animated custom emojis saved yet!")
        return

    await update.message.reply_text(
        f"Saved animated emojis ({len(animated_files)}):\n" + "\n".join(animated_files)
    )

async def save_animated_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages containing animated custom emojis"""
    message = update.message
    
    if not message.entities:
        await message.reply_text("No custom emojis found in this message.")
        return

    animated_emojis = []
    # First pass: identify all custom emojis
    custom_emoji_ids = []
    for entity in message.entities:
        if entity.type == "custom_emoji":
            custom_emoji_ids.append(entity.custom_emoji_id)

    if not custom_emoji_ids:
        await message.reply_text("No custom emojis found in this message.")
        return

    # Get all stickers at once (more efficient)
    try:
        emoji_stickers = await context.bot.get_custom_emoji_stickers(
            custom_emoji_ids=custom_emoji_ids
        )
    except Exception as e:
        await message.reply_text(f"Error accessing sticker sets: {str(e)}")
        return

    # Filter for animated emojis
    emoji_map = {sticker.custom_emoji_id: sticker for sticker in emoji_stickers}
    for emoji_id in custom_emoji_ids:
        sticker = emoji_map.get(emoji_id)
        if sticker and (sticker.is_animated or sticker.is_video):
            animated_emojis.append((emoji_id, sticker))

    if not animated_emojis:
        await message.reply_text("No animated custom emojis found in this message.")
        return

    success_count = 0
    fail_count = 0

    for emoji_id, sticker in animated_emojis:
        try:
            # Download sticker file
            file = await context.bot.get_file(sticker.file_id)
            file_bytes = await file.download_as_bytearray()

            # Save animated emoji in TGS format
            filename = f"emoji_{emoji_id}.tgs"
            save_path = os.path.join(ANIMATED_DIR, filename)
            with open(save_path, "wb") as f:
                f.write(file_bytes)
            
            success_count += 1

        except Exception as e:
            print(f"Error saving animated emoji {emoji_id}: {str(e)}")
            fail_count += 1

    await message.reply_text(
        f"Processed {len(animated_emojis)} animated custom emoji(s):\n"
        f"Successfully saved: {success_count}\n"
        f"Failed: {fail_count}"
    )

def main():
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_emojis))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_animated_emoji))

    # Start the bot
    print("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()