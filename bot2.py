import asyncio
import logging
import os
import random
import time
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from queue import Queue
from collections import defaultdict

# Load .env file
load_dotenv()

# Constants from .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = ""  # Leave empty for polling

# Gemini setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Load context from file
def load_context():
    try:
        with open("context.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error("context.txt not found!")
        return "Default context: I’m a support bot for THEFLASH47. How can I assist you?"

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Response cache and message queue
RESPONSE_CACHE = {}
PENDING_MESSAGES = defaultdict(list)  # Store messages per chat_id
LAST_SENT = {}  # Rate limiting tracker

async def notify_owner(message):
    """Notify the owner of errors."""
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": OWNER_CHAT_ID, "text": message})
    except Exception as e:
        logger.error(f"Failed to notify owner: {str(e)}")

async def set_webhook():
    """Set up a webhook for receiving updates."""
    try:
        payload = {"url": WEBHOOK_URL, "allowed_updates": ["message", "business_connection", "business_message"]}
        response = requests.post(f"{TELEGRAM_API_URL}/setWebhook", json=payload)
        response.raise_for_status()
        logger.info(f"Webhook set successfully: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {str(e)}")
        await notify_owner(f"Failed to set webhook: {str(e)}")

async def generate_response(prompt):
    """Generate AI response with caching."""
    if prompt in RESPONSE_CACHE:
        logger.info("Using cached response")
        return RESPONSE_CACHE[prompt]
    try:
        response = model.generate_content(prompt)
        RESPONSE_CACHE[prompt] = response.text
        return response.text
    except Exception as e:
        logger.error(f"AI generation error: {str(e)}")
        return "Oops, something went wrong! Please wait for THEFLASH47 to assist you."

async def send_message(chat_id, text, is_business=False):
    """Send message with typing indicator and rate limiting."""
    # Rate limiting: 1-second cooldown per chat
    if chat_id in LAST_SENT and (time.time() - LAST_SENT[chat_id]) < 1:
        await asyncio.sleep(1 - (time.time() - LAST_SENT[chat_id]))

    # Show typing indicator
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
    except Exception as e:
        logger.error(f"Failed to send typing action: {str(e)}")

    # Human-like delay
    delay = random.uniform(1.0, 3.0)
    await asyncio.sleep(delay)

    # Send message
    payload = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        response.raise_for_status()
        logger.info(f"{'Inbox' if is_business else 'Direct'} message sent (chat_id={chat_id}): {text}")
        LAST_SENT[chat_id] = time.time()
    except Exception as e:
        logger.error(f"Failed to send message: {str(e)}")
        await notify_owner(f"Send message failed: {str(e)}")

async def process_messages(chat_id, messages, is_business=False):
    """Process and reply to batched messages."""
    if not messages:
        return

    context = load_context()  # Load fresh context
    if len(messages) == 1:
        prompt = f"{context}\nUser question: {messages[0]['text']}"
    else:
        combined = "\n".join([f"- {msg['text']}" for msg in messages])
        prompt = f"{context}\nUser questions:\n{combined}\n\nProvide a single response addressing all questions."

    response = await generate_response(prompt)
    await send_message(chat_id, response, is_business)

async def handle_pending_messages():
    """Check and process pending messages after a delay."""
    while True:
        await asyncio.sleep(10)  # Check every 10 seconds
        current_time = time.time()
        for chat_id in list(PENDING_MESSAGES.keys()):
            messages = PENDING_MESSAGES[chat_id]
            if messages and (current_time - messages[-1]["timestamp"]) >= 120:  # 2 minutes
                is_business = messages[0]["is_business"]
                await process_messages(chat_id, messages, is_business)
                del PENDING_MESSAGES[chat_id]

async def process_update(update):
    """Process incoming Telegram updates and queue messages."""
    print(f"Raw update: {update}")

    # Business message
    if "business_message" in update:
        msg = update["business_message"]
        chat_id = msg["chat"]["id"]
        PENDING_MESSAGES[chat_id].append({"text": msg["text"], "timestamp": time.time(), "is_business": True})

    # Direct message
    elif "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_message = msg["text"]
        if user_message == "/start":
            await send_message(chat_id, "Hi! I’m your support bot, powered by Gemini. How can I help you today?")
        else:
            PENDING_MESSAGES[chat_id].append({"text": user_message, "timestamp": time.time(), "is_business": False})

async def long_polling():
    """Start long polling to receive updates from Telegram."""
    asyncio.create_task(handle_pending_messages())  # Start message batching task
    last_update_id = None
    while True:
        try:
            params = {"timeout": 60, "allowed_updates": ["message", "business_connection", "business_message"]}
            if last_update_id:
                params["offset"] = last_update_id + 1

            response = requests.get(f"{TELEGRAM_API_URL}/getUpdates", params=params, timeout=70)
            response.raise_for_status()
            updates = response.json().get("result", [])

            tasks = [process_update(update) for update in updates]
            if tasks:
                await asyncio.gather(*tasks)
                last_update_id = updates[-1]["update_id"]

        except Exception as e:
            logger.error(f"Error in long polling: {str(e)}")
            await notify_owner(f"Error in long polling: {str(e)}")
            await asyncio.sleep(5)

async def main():
    """Start the bot and begin polling or webhook setup."""
    logger.info("Bot is starting...")
    if WEBHOOK_URL:
        await set_webhook()
        logger.info("Webhook mode enabled. Please deploy the bot with a webhook server.")
    else:
        await long_polling()

if __name__ == "__main__":
    asyncio.run(main())
