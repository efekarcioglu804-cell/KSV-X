import os
from dotenv import load_dotenv

# .env dosyasındaki verileri sisteme yükler
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
VIP_CHANNEL = os.getenv("VIP_CHANNEL_ID")

if not BOT_TOKEN:
    raise ValueError("KRALIM DIKKAT! BOT_TOKEN bulunamadi, .env dosyasini kontrol et.")
