import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Your bot token from @BotFather
TOKEN = "7421685682:AAG6HfR2x9Vw42XAYJVUUGSC7gWKpD78BtU"

# Directory to save normal (non-animated) emojis in WebP format
STATIC_DIR = "custom_static_emojis_webp"
os.makedirs(STATIC_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "Welcome! Send me messages with non-animated custom emojis, and I'll save them in WebP format.\n"
        "Note: I only save non-animated custom emojis from accessible sticker sets.\n"
        "Animated custom emojis will be ignored.\n"
        "Use /list to see saved static emojis."
    )

async def list_emojis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all saved static emojis"""
    static_files = os.listdir(STATIC_DIR)
    
    if not static_files:
        await update.message.reply_text("No non-animated custom emojis saved yet!")
        return

    await update.message.reply_text(
        f"Saved non-animated emojis ({len(static_files)}):\n" + "\n".join(static_files)
    )

async def save_static_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages containing non-animated custom emojis"""
    message = update.message
    
    if not message.entities:
        await message.reply_text("No custom emojis found in this message.")
        return

    static_emojis = []
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

    # Filter for non-animated emojis
    emoji_map = {sticker.custom_emoji_id: sticker for sticker in emoji_stickers}
    for emoji_id in custom_emoji_ids:
        sticker = emoji_map.get(emoji_id)
        if sticker and not (sticker.is_animated or sticker.is_video):
            static_emojis.append((emoji_id, sticker))

    if not static_emojis:
        await message.reply_text("No non-animated custom emojis found in this message.")
        return

    success_count = 0
    fail_count = 0

    for emoji_id, sticker in static_emojis:
        try:
            # Download sticker file (already in WebP format)
            file = await context.bot.get_file(sticker.file_id)
            file_bytes = await file.download_as_bytearray()

            # Save directly in WebP format
            filename = f"emoji_{emoji_id}.webp"
            save_path = os.path.join(STATIC_DIR, filename)
            with open(save_path, "wb") as f:
                f.write(file_bytes)
            
            success_count += 1

        except Exception as e:
            print(f"Error saving static emoji {emoji_id}: {str(e)}")
            fail_count += 1

    await message.reply_text(
        f"Processed {len(static_emojis)} non-animated custom emoji(s):\n"
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_static_emoji))

    # Start the bot
    print("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
