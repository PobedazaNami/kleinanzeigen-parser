import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load env in this order:
# 1) If MINIAPP_ENV_FILE is set, load it with override=True
# 2) Otherwise load base .env (if exists)
# 3) Then load miniapp/.env (if exists) with override=True (project-local overrides)
# 4) Then load .env.miniapp at project root (if exists) with override=True
custom_env = os.getenv("MINIAPP_ENV_FILE")
if custom_env and os.path.exists(custom_env):
    load_dotenv(dotenv_path=custom_env, override=True)
else:
    # base .env (fallback)
    load_dotenv()
    # project root .env.miniapp (global overrides)
    mini_path = Path(__file__).resolve().parents[1] / ".env.miniapp"
    if mini_path.exists():
        load_dotenv(dotenv_path=str(mini_path), override=True)
    # miniapp/.env (local overrides win last)
    local_env = Path(__file__).resolve().parent / ".env"
    if local_env.exists():
        load_dotenv(dotenv_path=str(local_env), override=True)

# Mongo: prefer MINIAPP_*, then generic MONGODB_*, then legacy MONGO_*
MONGODB_URI = (
    os.getenv("MINIAPP_MONGODB_URI")
    or os.getenv("MONGODB_URI")
    or os.getenv("MONGO_URI")
    or "mongodb://localhost:27017"
)
MONGODB_DB = (
    os.getenv("MINIAPP_MONGODB_DB")
    or os.getenv("MONGODB_DB")
    or os.getenv("MONGO_DB_NAME")
    or "kleinanzeigen"
)

# Telegram: prefer MINIAPP_* to avoid clashing with existing bot
TELEGRAM_BOT_TOKEN = (
    os.getenv("MINIAPP_TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN", "")
)
TELEGRAM_ADMIN_CHAT_ID = (
    os.getenv("MINIAPP_TELEGRAM_ADMIN_CHAT_ID")
    or os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
)
TELEGRAM_FALLBACK_CHAT_ID = (
    os.getenv("MINIAPP_TELEGRAM_CHAT_ID")
    or os.getenv("TELEGRAM_CHAT_ID", "")
)

NOTIFY_INTERVAL_MINUTES = int(os.getenv("NOTIFY_INTERVAL_MINUTES", "30"))
SCHED_START_HOUR = int(os.getenv("SCHED_START_HOUR", "6"))
SCHED_END_HOUR = int(os.getenv("SCHED_END_HOUR", "23"))

SUBSCRIPTION_DURATION = timedelta(days=30)
TRIAL_DURATION = timedelta(days=14)

USER_DAILY_LIMIT = int(os.getenv("USER_DAILY_LIMIT", "50"))

# Simple http headers for minimal scraping
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.1 Safari/537.36"
    )
}

# Firecrawl (optional, used primarily for Immowelt)
FIRECRAWL_API_KEY = (
    os.getenv("MINIAPP_FIRECRAWL_API_KEY")
    or os.getenv("FIRECRAWL_API_KEY")
    or ""
)
IMMOWELT_USE_FIRECRAWL = os.getenv("IMMOWELT_USE_FIRECRAWL", "true").lower() in ("1", "true", "yes")

# Debug stats: when true, send per-run found/sent/filtered stats to admin chat
DEBUG_STATS = (
    os.getenv("MINIAPP_DEBUG_STATS")
    or os.getenv("DEBUG_STATS")
    or "false"
).lower() in ("1", "true", "yes")

# Support contact (e.g., @username or any text); falls back to admin chat id if set
# Explicit default handle for support if nothing provided
SUPPORT_CONTACT = (
    os.getenv("MINIAPP_SUPPORT_CONTACT")
    or os.getenv("SUPPORT_CONTACT")
    or "@reeziat"  # fallback explicit username
)
