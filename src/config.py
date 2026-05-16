import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "Money_trackeer_bot")
SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme")
DB_PATH: str = os.getenv("DB_PATH", "/app/data/finance_bot.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
TIMEZONE: str = os.getenv("TIMEZONE", "Africa/Cairo")

_raw = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set[int] = {
    int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()
}
