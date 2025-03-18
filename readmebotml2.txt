# Kill any existing ngrok or ssh processes
pkill -9 ngrok
pkill -9 ssh

# Clear old Serveo log
echo "" > /home/pi/telegram-bot/telegram-bot/serveo_output.log

# Start Serveo with a custom subdomain (replace 'mybot' with your choice)
nohup ssh -R mybot.serveo.net:80:localhost:8443 serveo.net > /home/pi/telegram-bot/telegram-bot/serveo_output.log 2>&1 &

# Wait for Serveo to initialize
sleep 10

# Check the Serveo log
cat /home/pi/telegram-bot/telegram-bot/serveo_output.log

# Expected output: Forwarding HTTP traffic from https://mybot.serveo.net.
# Webhook URL: https://mybot.serveo.net.

# Step 2: Update .env
nano /home/pi/telegram-bot/telegram-bot/.env

TELEGRAM_TOKEN=<your-bot-token>
WEBHOOK_URL=https://mybot.serveo.net
GEMINI_API_KEY=<your-gemini-api-key>
OWNER_CHAT_ID=<your-chat-id>

# Replace placeholders with your actual values.
# Save and exit (Ctrl+O, Enter, Ctrl+X).

#Step 3: Install Dependencies
#Ensure all required libraries are installed:
source /home/pi/telegram-bot/telegram-bot/venv/bin/activate
pip install aiogram google-generativeai python-dotenv
pip freeze > /home/pi/telegram-bot/telegram-bot/requirements.txt

# Step 4: Updated botml2.py with Serveo
# Here’s the adapted code from your GitHub link, integrated with Serveo:

#Key Changes:
#Simplified webhook setup to use Serveo’s URL from .env.
#Kept your Gemini AI integration and command handlers intact.
#Uses aiogram’s webhook mode with aiohttp.


# Kill any existing bot processes
pkill -9 -f botml2.py

# Clear old bot log
echo "" > /home/pi/telegram-bot/telegram-bot/bot_output.log

# Start bot with nohup
source /home/pi/telegram-bot/telegram-bot/venv/bin/activate
nohup /home/pi/telegram-bot/telegram-bot/venv/bin/python /home/pi/telegram-bot/telegram-bot/botml2.py > /home/pi/telegram-bot/telegram-bot/bot_output.log 2>&1 &

# Wait a few seconds
sleep 5

# Step 6: Verify

# Check Serveo process
ps aux | grep ssh
# Check bot process
ps aux | grep botml2.py
# Check Serveo log
cat /home/pi/telegram-bot/telegram-bot/serveo_output.log
# Check bot log
cat /home/pi/telegram-bot/telegram-bot/bot_output.log
# Check port usage
sudo lsof -i :8443

#Step 7: Test
#Send /start or a message to your bot on Telegram.
#Check bot_output.log for logs like:
2025-03-15 21:XX:XX,XXX - INFO - Webhook set to https://mybot.serveo.net
2025-03-15 21:XX:XX,XXX - INFO - Webhook server started on port 8443



Troubleshooting
Serveo Log Empty:
Run without nohup to debug:
bash

ssh -R mybot.serveo.net:80:localhost:8443 serveo.net

Check for network issues or port conflicts.

Bot Not Responding:
Ensure context.txt exists in /home/pi/telegram-bot/telegram-bot/.

Check bot_output.log for errors (e.g., webhook not set).

SSH Disconnects:
Install autossh for persistence:
bash

sudo apt install autossh
nohup autossh -M 0 -R mybot.serveo.net:80:localhost:8443 serveo.net > /home/pi/telegram-bot/telegram-bot/serveo_output.log 2>&1 &


