import requests
import sys
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TOPIC_ID = os.getenv('TELEGRAM_SCANNER_TOPIC_ID')

message = """🧪 TEST MESSAGE TO TOPIC
━━━━━━━━━━━━━━━━━━━━━━━━━━
Testing sending message to specific topic (H1).
━━━━━━━━━━━━━━━━━━━━━━━━━━"""

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
payload = {
    'chat_id': CHAT_ID,
    'text': message,
    'parse_mode': 'HTML'
}

if TOPIC_ID:
    payload['message_thread_id'] = int(TOPIC_ID)
    print(f"Sending to topic ID: {TOPIC_ID}")
else:
    print("No topic ID found in .env")

try:
    response = requests.post(url, json=payload, timeout=10)
    if response.status_code == 200:
        print("SUCCESS! Pesan terkirim ke Telegram!")
    else:
        print(f"ERROR: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"ERROR: {e}")
