import asyncio
import json
import logging
import os
import time
import requests
from dotenv import load_dotenv
import google.generativeai as genai

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Set this if deploying with webhooks

# Configure Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Load context from file
def load_context():
    with open("context.txt", "r") as f:
        return f.read()

CONTEXT = load_context()

# Telegram API base URL
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

async def notify_owner(message: str):
    """Notify the owner of errors or manual intervention needs."""
    try:
        payload = {
            "chat_id": OWNER_CHAT_ID,
            "text": message
        }
        response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        response.raise_for_status()
        logger.info(f"Notified owner: {message}")
    except Exception as e:
        logger.error(f"Failed to notify owner: {str(e)}")

def generate_response_with_retry(prompt: str, max_retries: int = 3):
    """Generate a response with retry logic for API failures."""
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            return response
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            raise e

async def send_message(chat_id: str, text: str, business_connection_id: str = None):
    """Send a message to a chat, optionally via a business connection."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id

        response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        response.raise_for_status()
        logger.info(f"Sent message to chat {chat_id}: {text}")
    except Exception as e:
        logger.error(f"Failed to send message to chat {chat_id}: {str(e)}")
        await notify_owner(f"Failed to send message to chat {chat_id}: {str(e)}")

async def send_chat_action(chat_id: str, action: str, business_connection_id: str = None):
    """Send a chat action (e.g., typing) to a chat, optionally via a business connection."""
    try:
        payload = {
            "chat_id": chat_id,
            "action": action
        }
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id

        response = requests.post(f"{TELEGRAM_API_URL}/sendChatAction", json=payload)
        response.raise_for_status()
        logger.info(f"Sent chat action {action} to chat {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send chat action to chat {chat_id}: {str(e)}")

async def handle_business_connection(update: dict):
    """Handle business connection updates."""
    business_connection = update.get("business_connection", {})
    if not business_connection:
        return

    logger.info(
        f"Business Connection: ID={business_connection.get('id')}, "
        f"User={business_connection.get('user', {}).get('id')}, "
        f"Can Reply={business_connection.get('can_reply')}, "
        f"Disabled={business_connection.get('is_enabled') is False}"
    )

async def handle_business_message(update: dict):
    """Handle business messages from users, generating responses using Gemini AI."""
    business_message = update.get("business_message", {})
    if not business_message:
        return

    chat_id = str(business_message["chat"]["id"])
    business_connection_id = business_message.get("business_connection_id")
    user_message = business_message.get("text", "")

    if not user_message:
        await send_message(
            chat_id,
            "Sorry, I can only process text messages. Please wait for THEFLASH47 to assist you.",
            business_connection_id
        )
        return

    await send_chat_action(chat_id, "typing", business_connection_id)
    prompt = f"{CONTEXT}\nUser question: {user_message}"
    try:
        response = generate_response_with_retry(prompt)
        await send_message(chat_id, response.text, business_connection_id)
    except Exception as e:
        logger.error(f"Error handling business message from chat {chat_id}: {str(e)}")
        await notify_owner(f"Error handling business message from chat {chat_id}: {str(e)}")
        if "rate limit" in str(e).lower():
            await send_message(
                chat_id,
                "I'm currently handling many requests. Please try again in a few minutes!",
                business_connection_id
            )
        else:
            await send_message(
                chat_id,
                "Oops, something went wrong! Please wait for THEFLASH47 to assist you.",
                business_connection_id
            )

async def handle_direct_message(update: dict):
    """Handle direct messages from users, generating responses using Gemini AI."""
    message = update.get("message", {})
    if not message:
        return

    chat_id = str(message["chat"]["id"])
    user_message = message.get("text", "")

    # Handle /start command
    if user_message.startswith("/start"):
        user_name = message["from"]["first_name"]
        welcome_text = f"Hi {user_name}! I’m your support bot, powered by Gemini. How can I help you today?"
        await send_message(chat_id, welcome_text)
        return

    # Handle non-text messages
    if not user_message:
        await send_message(
            chat_id,
            "Sorry, I can only process text messages. Please wait for THEFLASH47 to assist you."
        )
        return

    await send_chat_action(chat_id, "typing")
    prompt = f"{CONTEXT}\nUser question: {user_message}"
    try:
        response = generate_response_with_retry(prompt)
        await send_message(chat_id, response.text)
    except Exception as e:
        logger.error(f"Error handling direct message from chat {chat_id}: {str(e)}")
        await notify_owner(f"Error handling direct message from chat {chat_id}: {str(e)}")
        if "rate limit" in str(e).lower():
            await send_message(
                chat_id,
                "I'm currently handling many requests. Please try again in a few minutes!"
            )
        else:
            await send_message(
                chat_id,
                "Oops, something went wrong! Please wait for THEFLASH47 to assist you."
            )

async def process_update(update: dict):
    """Process incoming updates from Telegram."""
    if "business_connection" in update:
        await handle_business_connection(update)
    elif "business_message" in update:
        await handle_business_message(update)
    elif "message" in update:
        await handle_direct_message(update)
    else:
        logger.warning(f"Unhandled update type: {update}")

async def set_webhook():
    """Set up a webhook for receiving updates."""
    try:
        payload = {
            "url": WEBHOOK_URL,
            "allowed_updates": ["message", "business_connection", "business_message"]
        }
        response = requests.post(f"{TELEGRAM_API_URL}/setWebhook", json=payload)
        response.raise_for_status()
        logger.info(f"Webhook set successfully: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {str(e)}")
        await notify_owner(f"Failed to set webhook: {str(e)}")

async def long_polling():
    """Start long polling to receive updates from Telegram."""
    last_update_id = None
    while True:
        try:
            params = {"timeout": 60, "allowed_updates": ["message", "business_connection", "business_message"]}
            if last_update_id:
                params["offset"] = last_update_id + 1

            response = requests.get(f"{TELEGRAM_API_URL}/getUpdates", params=params, timeout=70)
            response.raise_for_status()
            updates = response.json().get("result", [])

            for update in updates:
                last_update_id = update["update_id"]
                await process_update(update)

        except Exception as e:
            logger.error(f"Error in long polling: {str(e)}")
            await notify_owner(f"Error in long polling: {str(e)}")
            await asyncio.sleep(5)  # Wait before retrying

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
