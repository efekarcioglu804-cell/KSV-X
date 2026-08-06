import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("TELEGRAM_API_ID", 0))
API_HASH = os.getenv("TELEGRAM_API_HASH")
VIP_CHANNEL = int(os.getenv("VIP_CHANNEL_ID", 0))

if not BOT_TOKEN:
    raise ValueError("KRALIM DIKKAT! BOT_TOKEN bulunamadi, .env dosyasini kontrol et.")
