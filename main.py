import os
import sys
import subprocess
from threading import Thread
from flask import Flask
import requests # Added for optional external IP check

# Function to run the bot.py script
def run_bot():
    # IMPORTANT: If your bot's main file is named 'CryptoBot.py' (or 'Bot.py'),
    # change "bot.py" below to its exact filename (case-sensitive).
    subprocess.run([sys.executable, "bot.py"]) 

# Start the bot.py script in a separate thread
# This prevents the Flask web server from blocking your Discord bot's operations
bot_thread = Thread(target=run_bot)
bot_thread.start()

# This is a dummy Flask app that Render will detect and use to provide a public URL.
# Your Discord bot's logic runs independently in 'bot.py'.
app = Flask(__name__)

@app.route('/')
def home():
    # Optional: Try to get the external IP when this route is accessed
    # This can help confirm if the IP has changed, but isn't essential for bot operation.
    try:
        external_ip = requests.get('https://api.ipify.org').text
        return f"Your Discord Bot's Web Server is Active! External IP: {external_ip}"
    except Exception:
        return "Your Discord Bot's Web Server is Active! (Could not get external IP)"


@app.route('/pong')
def pong_check():
    return "Pong!"

# Render expects the web service to listen on the port specified by the PORT environment variable.
# If not set, it defaults to 8080.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

