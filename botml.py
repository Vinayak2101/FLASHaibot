import asyncio
import json
import logging
import os
import time
import requests
from dotenv import load_dotenv
import google.generativeai as genai
from telegram_inline import InlineKeyboardMarkup, InlineKeyboardButton

# Configure logging with DEBUG level for troubleshooting
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Set this if deploying with webhooks

# Log the loaded OWNER_CHAT_ID to verify
logger.debug(f"Loaded OWNER_CHAT_ID: {OWNER_CHAT_ID}")

# Configure Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Load initial context from file
def load_context():
    with open("context.txt", "r") as f:
        return f.read()

CONTEXT = load_context()
LEARNED_CONTEXT = ""  # Dynamically updated context based on feedback

# Telegram API base URL
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Store chat history and feedback in memory (consider using a database for production)
CHAT_HISTORY = {}  # {chat_id: [{"role": "user", "content": "..."}, {"role": "bot", "content": "..."}]}
FEEDBACK_DATA = {}  # {message_id: {"chat_id": "...", "user_message": "...", "bot_response": "...", "feedback": "positive/negative"}}

# Track blocked chats
BLOCKED_CHATS = set()

# Delay before sending replies (in seconds)
REPLY_DELAY = 2

# Persistent offset storage
OFFSET_FILE = "last_update_id.txt"

def load_last_update_id():
    """Load the last processed update ID from file."""
    try:
        with open(OFFSET_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None

def save_last_update_id(update_id):
    """Save the last processed update ID to file."""
    with open(OFFSET_FILE, "w") as f:
        f.write(str(update_id))

async def notify_owner(message: str):
    """Notify the owner of errors or manual intervention needs."""
    try:
        payload = {"chat_id": OWNER_CHAT_ID, "text": message}
        response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        response.raise_for_status()
        logger.info(f"Notified owner: {message}")
        logger.debug(f"Notification sent to OWNER_CHAT_ID: {OWNER_CHAT_ID}")
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
                time.sleep(2 ** attempt)
                continue
            raise e

async def send_message(chat_id: str, text: str, business_connection_id: str = None, message_id: str = None):
    """Send a message with feedback buttons only for the owner."""
    if chat_id in BLOCKED_CHATS:
        logger.warning(f"Skipping message to blocked chat {chat_id}")
        return None

    try:
        await asyncio.sleep(REPLY_DELAY)
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id

        # Debug the chat_id vs OWNER_CHAT_ID comparison
        logger.debug(f"Chat ID: {chat_id}, Owner Chat ID: {OWNER_CHAT_ID}, Is Owner: {chat_id == OWNER_CHAT_ID}")

        # Only add feedback buttons if the chat is the owner's
        if chat_id == OWNER_CHAT_ID:
            feedback_id = message_id if message_id else str(time.time())
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👍", callback_data=f"feedback_positive_{feedback_id}"),
                    InlineKeyboardButton("👎", callback_data=f"feedback_negative_{feedback_id}")
                ]
            ])
            payload["reply_markup"] = json.dumps(keyboard.to_dict())
            logger.debug(f"Added feedback buttons for owner chat {chat_id}")
        else:
            logger.debug(f"No feedback buttons added for non-owner chat {chat_id}")

        response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        response.raise_for_status()
        logger.info(f"Sent message to chat {chat_id}: {text}")
        return response.json()["result"]["message_id"]
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            logger.error(f"Failed to send message to chat {chat_id}: {str(e)} - Chat may be blocked or restricted.")
            BLOCKED_CHATS.add(chat_id)
            await notify_owner(f"Chat {chat_id} blocked or restricted: {str(e)}")
        else:
            logger.error(f"Failed to send message to chat {chat_id}: {str(e)}")
            await notify_owner(f"Failed to send message to chat {chat_id}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Failed to send message to chat {chat_id}: {str(e)}")
        await notify_owner(f"Failed to send message to chat {chat_id}: {str(e)}")
        return None

async def send_chat_action(chat_id: str, action: str, business_connection_id: str = None):
    """Send a chat action (e.g., typing)."""
    if chat_id in BLOCKED_CHATS:
        logger.warning(f"Skipping chat action to blocked chat {chat_id}")
        return

    try:
        payload = {"chat_id": chat_id, "action": action}
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id

        response = requests.post(f"{TELEGRAM_API_URL}/sendChatAction", json=payload)
        response.raise_for_status()
        logger.info(f"Sent chat action {action} to chat {chat_id}")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            logger.error(f"Failed to send chat action to chat {chat_id}: {str(e)} - Chat may be blocked or restricted.")
            BLOCKED_CHATS.add(chat_id)
        else:
            logger.error(f"Failed to send chat action to chat {chat_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to send chat action to chat {chat_id}: {str(e)}")

async def handle_feedback(callback_query: dict):
    """Handle feedback from inline buttons, only from the owner."""
    data = callback_query["data"]
    message = callback_query["message"]
    chat_id = str(message["chat"]["id"])
    message_id = str(message["message_id"])
    user_message = CHAT_HISTORY[chat_id][-2]["content"] if len(CHAT_HISTORY[chat_id]) >= 2 else "Unknown"
    bot_response = message["text"]

    if chat_id != OWNER_CHAT_ID:
        logger.debug(f"Ignoring feedback from non-owner chat {chat_id}")
        return

    if data.startswith("feedback_positive"):
        feedback = "positive"
    elif data.startswith("feedback_negative"):
        feedback = "negative"
    else:
        return

    FEEDBACK_DATA[message_id] = {
        "chat_id": chat_id,
        "user_message": user_message,
        "bot_response": bot_response,
        "feedback": feedback
    }
    logger.info(f"Received {feedback} feedback for message {message_id} in chat {chat_id}")

    global LEARNED_CONTEXT
    if feedback == "positive":
        LEARNED_CONTEXT += f"\n\nUser: {user_message}\nBot: {bot_response}"
        logger.info(f"Updated learned context with: User: {user_message}, Bot: {bot_response}")

    try:
        payload = {"callback_query_id": callback_query["id"], "text": "Thanks for your feedback!"}
        response = requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json=payload)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to acknowledge feedback: {str(e)}")

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
    """Handle business messages with context-aware responses."""
    business_message = update.get("business_message", {})
    if not business_message or "text" not in business_message:
        logger.debug(f"No valid text in business message update: {json.dumps(update)}")
        return

    chat_id = str(business_message["chat"]["id"])
    if chat_id == OWNER_CHAT_ID:
        logger.debug(f"Ignoring business message from owner chat {chat_id}")
        return

    business_connection_id = business_message.get("business_connection_id")
    user_message = business_message.get("text", "").strip()

    if not user_message:
        message_id = await send_message(
            chat_id,
            "Sorry, I can only process text messages. Please wait for THEFLASH47 to assist you.",
            business_connection_id
        )
        return

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_message})
    await send_chat_action(chat_id, "typing", business_connection_id)

    history_text = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in CHAT_HISTORY[chat_id][-5:]])
    prompt = f"{CONTEXT}\n{LEARNED_CONTEXT}\n\nChat History:\n{history_text}\n\nUser question: {user_message}"

    try:
        response = generate_response_with_retry(prompt)
        message_id = await send_message(chat_id, response.text, business_connection_id)
        if message_id:
            CHAT_HISTORY[chat_id].append({"role": "bot", "content": response.text})
    except Exception as e:
        logger.error(f"Error handling business message from chat {chat_id}: {str(e)}")
        await notify_owner(f"Error handling business message from chat {chat_id}: {str(e)}")
        message_id = await send_message(
            chat_id,
            "Oops, something went wrong! Please wait for THEFLASH47 to assist you.",
            business_connection_id
        )

async def handle_direct_message(update: dict):
    """Handle direct messages with context-aware responses."""
    message = update.get("message", {})
    if not message or "text" not in message:
        logger.debug(f"No valid text in direct message update: {json.dumps(update)}")
        return

    chat_id = str(message["chat"]["id"])
    if chat_id == OWNER_CHAT_ID:
        logger.debug(f"Ignoring direct message from owner chat {chat_id}")
        return

    user_message = message.get("text", "").strip()
    message_timestamp = message.get("date", 0)  # Unix timestamp of the message

    # Only process messages sent after the bot started
    current_time = int(time.time())
    if message_timestamp < current_time - 60:  # Ignore messages older than 60 seconds
        logger.debug(f"Ignoring old message from chat {chat_id}: {user_message}")
        return

    if user_message.startswith("/start"):
        user_name = message["from"]["first_name"]
        welcome_text = f"Hi {user_name}! I’m your support bot, powered by Gemini. How can I help you today?"
        message_id = await send_message(chat_id, welcome_text)
        return

    if not user_message:
        message_id = await send_message(
            chat_id,
            "Sorry, I can only process text messages. Please wait for THEFLASH47 to assist you."
        )
        return

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_message})
    await send_chat_action(chat_id, "typing")

    history_text = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in CHAT_HISTORY[chat_id][-5:]])
    prompt = f"{CONTEXT}\n{LEARNED_CONTEXT}\n\nChat History:\n{history_text}\n\nUser question: {user_message}"

    try:
        response = generate_response_with_retry(prompt)
        message_id = await send_message(chat_id, response.text)
        if message_id:
            CHAT_HISTORY[chat_id].append({"role": "bot", "content": response.text})
    except Exception as e:
        logger.error(f"Error handling direct message from chat {chat_id}: {str(e)}")
        await notify_owner(f"Error handling direct message from chat {chat_id}: {str(e)}")
        message_id = await send_message(
            chat_id,
            "Oops, something went wrong! Please wait for THEFLASH47 to assist you."
        )

async def process_update(update: dict):
    """Process incoming updates from Telegram."""
    logger.debug(f"Processing update: {json.dumps(update)}")
    if "callback_query" in update:
        await handle_feedback(update["callback_query"])
    elif "business_connection" in update:
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
            "allowed_updates": ["message", "business_connection", "business_message", "callback_query"]
        }
        response = requests.post(f"{TELEGRAM_API_URL}/setWebhook", json=payload)
        response.raise_for_status()
        logger.info(f"Webhook set successfully: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {str(e)}")
        await notify_owner(f"Failed to set webhook: {str(e)}")

async def long_polling():
    """Start long polling to receive updates from Telegram."""
    last_update_id = load_last_update_id()
    processed_updates = set()

    while True:
        try:
            params = {"timeout": 60, "allowed_updates": ["message", "business_connection", "business_message", "callback_query"]}
            if last_update_id is not None:
                params["offset"] = last_update_id + 1

            response = requests.get(f"{TELEGRAM_API_URL}/getUpdates", params=params, timeout=70)
            response.raise_for_status()
            updates = response.json().get("result", [])

            if not updates:
                logger.debug("No new updates received.")
                continue

            for update in updates:
                update_id = update["update_id"]
                if update_id in processed_updates:
                    logger.warning(f"Skipping already processed update: {update_id}")
                    continue

                processed_updates.add(update_id)
                last_update_id = update_id
                await process_update(update)
                save_last_update_id(last_update_id)  # Save offset after processing

            if len(processed_updates) > 1000:
                processed_updates.clear()

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
