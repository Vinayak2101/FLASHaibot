import asyncio
import json
import logging
import os
import sqlite3
import time
import requests
from dotenv import load_dotenv
import google.generativeai as genai
from http.server import BaseHTTPRequestHandler, HTTPServer

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")  # Your chat ID (655037157)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., https://yourdomain.com/webhook

logger.debug(f"Loaded OWNER_CHAT_ID: {OWNER_CHAT_ID}")
logger.debug(f"Loaded WEBHOOK_URL: {WEBHOOK_URL}")

# Configure Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Load initial context from file
def load_context():
    with open("context.txt", "r") as f:
        return f.read()

CONTEXT = load_context()
LEARNED_CONTEXT = ""  # Dynamically updated with owner's messages

# Telegram API base URL
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# SQLite Database Setup
DB_FILE = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp REAL NOT NULL
    )''')
    conn.commit()
    conn.close()

init_db()

def save_message_to_db(chat_id, role, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO chat_history (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
              (chat_id, role, content, time.time()))
    conn.commit()
    conn.close()

def load_chat_history(chat_id, limit=5):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role, content FROM chat_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?",
              (chat_id, limit))
    history = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in history[::-1]]

# Track blocked chats
BLOCKED_CHATS = set()

# Delay before sending replies (in seconds)
REPLY_DELAY = 2

# Batch message queue
message_queue = []

async def notify_owner(message: str):
    """Notify the owner of errors or manual intervention needs."""
    await send_message(OWNER_CHAT_ID, message)

def generate_response_with_retry(prompt: str, max_retries: int = 3):
    """Generate a response with retry logic for API failures."""
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise e

async def send_message(chat_id: str, text: str, business_connection_id: str = None):
    """Queue a message for batch sending."""
    if chat_id in BLOCKED_CHATS:
        logger.warning(f"Skipping message to blocked chat {chat_id}")
        return None

    payload = {"chat_id": chat_id, "text": text}
    if business_connection_id:
        payload["business_connection_id"] = business_connection_id
    message_queue.append(payload)
    logger.debug(f"Queued message for chat {chat_id}: {text}")
    return str(time.time())  # Temporary message ID

async def flush_message_queue():
    """Send all queued messages in a batch."""
    global message_queue
    if not message_queue:
        return

    logger.debug(f"Flushing {len(message_queue)} messages from queue")
    for msg in message_queue:
        try:
            await asyncio.sleep(REPLY_DELAY)
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=msg)
            response.raise_for_status()
            logger.info(f"Sent message to chat {msg['chat_id']}: {msg['text']}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.error(f"Failed to send message to chat {msg['chat_id']}: {str(e)}")
                BLOCKED_CHATS.add(msg["chat_id"])
                await notify_owner(f"Chat {msg['chat_id']} blocked or restricted: {str(e)}")
            else:
                logger.error(f"Failed to send message to chat {msg['chat_id']}: {str(e)}")
                await notify_owner(f"Failed to send message to chat {msg['chat_id']}: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to send message to chat {msg['chat_id']}: {str(e)}")
            await notify_owner(f"Failed to send message to chat {msg['chat_id']}: {str(e)}")
    message_queue = []

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
    except Exception as e:
        logger.error(f"Failed to send chat action to chat {chat_id}: {str(e)}")

async def handle_business_message(update: dict):
    """Handle business messages with context-aware responses."""
    business_message = update.get("business_message", {})
    if not business_message or "text" not in business_message:
        logger.debug(f"No valid text in business message update: {json.dumps(update)}")
        return

    sender_id = str(business_message["from"]["id"])
    chat_id = str(business_message["chat"]["id"])

    # Ignore messages sent by the owner
    if sender_id == OWNER_CHAT_ID:
        logger.debug(f"Ignoring business message from owner (sender_id: {sender_id}) in chat {chat_id}")
        save_message_to_db(chat_id, "user", business_message["text"])
        global LEARNED_CONTEXT
        LEARNED_CONTEXT += f"\n\nOwner: {business_message['text']}"
        logger.info(f"Updated LEARNED_CONTEXT with owner's message: {business_message['text']}")
        return

    business_connection_id = business_message.get("business_connection_id")
    user_message = business_message.get("text", "").strip()

    if not user_message:
        await send_message(chat_id, "Sorry, I can only process text messages. Please wait for THEFLASH47 to assist you.", business_connection_id)
        return

    save_message_to_db(chat_id, "user", user_message)
    await send_chat_action(chat_id, "typing", business_connection_id)

    history = load_chat_history(chat_id)
    history_text = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])
    prompt = f"{CONTEXT}\n{LEARNED_CONTEXT}\n\nChat History:\n{history_text}\n\nUser question: {user_message}"

    try:
        response = generate_response_with_retry(prompt)
        await send_message(chat_id, response, business_connection_id)
        save_message_to_db(chat_id, "bot", response)
    except Exception as e:
        logger.error(f"Error handling business message from chat {chat_id}: {str(e)}")
        await notify_owner(f"Error handling business message from chat {chat_id}: {str(e)}")
        await send_message(chat_id, "Oops, something went wrong! Please wait for THEFLASH47 to assist you.", business_connection_id)

async def handle_direct_message(update: dict):
    """Handle direct messages with context-aware responses."""
    message = update.get("message", {})
    if not message or "text" not in message:
        logger.debug(f"No valid text in direct message update: {json.dumps(update)}")
        return

    sender_id = str(message["from"]["id"])
    chat_id = str(message["chat"]["id"])

    # Ignore messages sent by the owner and store them as context
    if sender_id == OWNER_CHAT_ID:
        logger.debug(f"Ignoring direct message from owner (sender_id: {sender_id}) in chat {chat_id}")
        save_message_to_db(chat_id, "user", message["text"])
        global LEARNED_CONTEXT
        LEARNED_CONTEXT += f"\n\nOwner: {message['text']}"
        logger.info(f"Updated LEARNED_CONTEXT with owner's message: {message['text']}")
        return

    user_message = message.get("text", "").strip()
    message_timestamp = message.get("date", 0)

    current_time = int(time.time())
    if message_timestamp < current_time - 60:
        logger.debug(f"Ignoring old message from chat {chat_id}: {user_message}")
        return

    if user_message.startswith("/start"):
        user_name = message["from"]["first_name"]
        welcome_text = f"Hi {user_name}! I’m your support bot, powered by Gemini. How can I help you today?"
        await send_message(chat_id, welcome_text)
        save_message_to_db(chat_id, "bot", welcome_text)
        return

    if not user_message:
        await send_message(chat_id, "Sorry, I can only process text messages. Please wait for THEFLASH47 to assist you.")
        return

    save_message_to_db(chat_id, "user", user_message)
    await send_chat_action(chat_id, "typing")

    history = load_chat_history(chat_id)
    history_text = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in history])
    prompt = f"{CONTEXT}\n{LEARNED_CONTEXT}\n\nChat History:\n{history_text}\n\nUser question: {user_message}"

    try:
        response = generate_response_with_retry(prompt)
        await send_message(chat_id, response)
        save_message_to_db(chat_id, "bot", response)
    except Exception as e:
        logger.error(f"Error handling direct message from chat {chat_id}: {str(e)}")
        await notify_owner(f"Error handling direct message from chat {chat_id}: {str(e)}")
        await send_message(chat_id, "Oops, something went wrong! Please wait for THEFLASH47 to assist you.")

async def process_update(update: dict):
    """Process incoming updates from Telegram."""
    logger.debug(f"Processing update: {json.dumps(update)}")
    if "business_message" in update:
        await handle_business_message(update)
    elif "message" in update:
        await handle_direct_message(update)
    await flush_message_queue()  # Flush queue after each update

# Webhook Server
class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        update = json.loads(post_data.decode('utf-8'))
        asyncio.run_coroutine_threadsafe(process_update(update), loop)
        self.send_response(200)
        self.end_headers()

async def set_webhook():
    """Set up the webhook with Telegram."""
    try:
        payload = {
            "url": WEBHOOK_URL,
            "allowed_updates": ["message", "business_message"]
        }
        response = requests.post(f"{TELEGRAM_API_URL}/setWebhook", json=payload)
        response.raise_for_status()
        logger.info(f"Webhook set successfully: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {str(e)}")
        await notify_owner(f"Failed to set webhook: {str(e)}")

async def start_webhook_server():
    """Start the webhook server."""
    server = HTTPServer(('0.0.0.0', 8443), WebhookHandler)
    logger.info("Starting webhook server on port 8443...")
    await asyncio.to_thread(server.serve_forever)

async def main():
    """Start the bot with webhook support."""
    global loop
    loop = asyncio.get_running_loop()
    logger.info("Bot is starting...")
    await set_webhook()
    await start_webhook_server()

if __name__ == "__main__":
    asyncio.run(main())
