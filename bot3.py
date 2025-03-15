from google.generativeai import configure, chat
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import os
from collections import defaultdict, deque

# Load the API key and context
API_KEY = "YOUR_GEMINI_API_KEY"
CONTEXT_FILE = "context.txt"

# Configure Gemini AI
configure(api_key=API_KEY)

def load_context():
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        return f.read()

CONTEXT = load_context()

# Store chat history (last 5 messages per user)
user_chat_history = defaultdict(lambda: deque(maxlen=5))

def generate_response(user_id, user_message):
    """Generates a response using Gemini AI with chat history."""
    
    # Retrieve user chat history
    history = "\n".join(user_chat_history[user_id])
    
    # Append new message to history
    user_chat_history[user_id].append(f"User: {user_message}")
    
    # Construct the prompt with context and history
    prompt = f"{CONTEXT}\nChat history:\n{history}\nUser: {user_message}"
    
    # Get AI response
    response = chat(prompt)
    
    # Store bot response in history
    user_chat_history[user_id].append(f"Bot: {response}")
    
    return response

def handle_message(update: Update, context: CallbackContext):
    """Handles incoming messages from users."""
    user_id = update.message.chat_id
    user_message = update.message.text
    response = generate_response(user_id, user_message)
    update.message.reply_text(response)

def main():
    """Main function to run the bot."""
    TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
