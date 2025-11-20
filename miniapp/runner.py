from typing import List, Dict
from datetime import datetime, timedelta
import pytz
import asyncio
import logging
from telegram.ext import Application
from .config import (
    NOTIFY_INTERVAL_MINUTES,
    SCHED_START_HOUR,
    SCHED_END_HOUR,
    TELEGRAM_FALLBACK_CHAT_ID,
    TELEGRAM_ADMIN_CHAT_ID,
    DEBUG_STATS,
    SUPPORT_CONTACT,
)
from telegram import Bot

from .user_manager import UserManager
from .parsers.kleinanzeigen import KleinanzeigenParser
from .parsers.immowelt import ImmoweltParser
from .config import (
    NOTIFY_INTERVAL_MINUTES,
    SCHED_START_HOUR,
    SCHED_END_HOUR,
    TELEGRAM_FALLBACK_CHAT_ID,
    TELEGRAM_ADMIN_CHAT_ID,
    DEBUG_STATS,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

um = UserManager()
application: Application | None = None

def berlin_now():
    tz = pytz.timezone('Europe/Berlin')
    return datetime.now(tz)


def match_location(addr: str, preferred: List[str]) -> bool:
    # If no user preferences, everything matches
    if not preferred:
        return True
    # If listing has no detectable address, don't over-filter: allow it
    if not addr:
        return True
    low = addr.lower()
    for p in preferred:
        if p.strip().lower() in low:
            return True
    return False


def _extract_location_from_url(url: str) -> str:
    """Extract location/city name from search URL for display purposes."""
    from urllib.parse import urlparse
    try:
        # Try to extract city/location from URL path
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        # For kleinanzeigen: /s-wohnung-mieten/darmstadt/...
        # For immowelt: /liste/darmstadt/...
        if len(path_parts) >= 2:
            # Second part is usually the city
            return path_parts[1]
        # If can't extract, return domain
        domain = parsed.netloc.replace('www.', '')
        return domain
    except Exception:
        return "unknown"


def _format_admin_notification(user_id: str, user_data: Dict, per_url_stats: Dict[str, Dict], new_found: int) -> str:
    """Format a readable admin notification about user's apartment search results.
    
    Args:
        user_id: User's Telegram ID
        user_data: Dict with user info (username, first_name, last_name)
        per_url_stats: Statistics per URL (parsed, sent, filtered, dedup, limit)
        new_found: Total number of new apartments sent to user
        
    Returns:
        Formatted notification message
    """
    from urllib.parse import urlparse
    
    # Build user identifier
    username = user_data.get("username", "")
    first_name = user_data.get("first_name", "")
    
    if username:
        user_display = f"@{username}"
    elif first_name:
        user_display = first_name
    else:
        user_display = f"ID: {user_id}"
    
    # Header with result
    if new_found > 0:
        header = f"✅ Користувачу {user_display} надіслано {new_found} нов{'у' if new_found == 1 else 'их'} квартир{'у' if new_found == 1 else ''}"
    else:
        header = f"ℹ️ Користувач {user_display} - нових квартир не знайдено"
    
    lines = [header]
    
    # Process each URL
    for url, stats in per_url_stats.items():
        location = _extract_location_from_url(url)
        domain = urlparse(url).netloc.replace('www.', '')
        
        # Summary line for this URL
        total = stats['parsed']
        sent = stats['sent']
        filtered = stats['filtered']
        dedup = stats['dedup']
        limit_reached = stats['limit']
        
        # Only show stats if there were any results
        if total > 0:
            stats_parts = []
            stats_parts.append(f"знайдено: {total}")
            if sent > 0:
                stats_parts.append(f"✉️ надіслано: {sent}")
            if dedup > 0:
                stats_parts.append(f"дублі: {dedup}")
            if filtered > 0:
                stats_parts.append(f"відфільтровано: {filtered}")
            if limit_reached > 0:
                stats_parts.append(f"ліміт: {limit_reached}")
            
            lines.append(f"📍 {location} ({domain}): {' | '.join(stats_parts)}")
    
    return "\n".join(lines)


async def send_message(chat_id: str, text: str) -> bool:
    if not application:
        return False
    # Normalize whitespace: collapse multiple blank lines and trim lines
    def normalize_text(s: str) -> str:
        # unify newlines
        s = s.replace('\r\n', '\n').replace('\r', '\n')
        lines = [ln.rstrip() for ln in s.split('\n')]
        out_lines: list[str] = []
        empty = False
        for ln in lines:
            if ln.strip() == "":
                if not empty:
                    out_lines.append("")
                empty = True
            else:
                out_lines.append(ln.strip())
                empty = False
        # strip leading/trailing empty lines
        while out_lines and out_lines[0] == "":
            out_lines.pop(0)
        while out_lines and out_lines[-1] == "":
            out_lines.pop()
        return "\n".join(out_lines)
    try:
        await application.bot.send_message(chat_id=chat_id, text=normalize_text(text), disable_web_page_preview=True)
        return True
    except Exception:
        return False


async def async_run_cycle(ignore_window: bool = False):
    now = berlin_now()
    logger.info(f"🔄 Starting scheduled run cycle at {now.strftime('%Y-%m-%d %H:%M:%S')} Berlin time")
    
    if not ignore_window:
        if now.hour < SCHED_START_HOUR:
            logger.info(f"⏸️ Skipping - outside schedule window (before {SCHED_START_HOUR}:00)")
            return
        if now.hour > SCHED_END_HOUR or (now.hour == SCHED_END_HOUR and now.minute > 30):
            logger.info(f"⏸️ Skipping - outside schedule window (after {SCHED_END_HOUR}:30)")
            return
    
    users = um.get_active_users()
    if not users and TELEGRAM_FALLBACK_CHAT_ID:
        users = [{"user_id": TELEGRAM_FALLBACK_CHAT_ID, "username": "fallback", "role": "user"}]
    
    logger.info(f"👥 Processing {len(users)} active user(s)")

    parsers_map = {
        "kleinanzeigen.de": KleinanzeigenParser(),
        "immowelt.de": ImmoweltParser(),
    }
    parsed_cache: dict[str, list] = {}
    for u in users:
        logger.info(f"🔍 Processing user {u.get('user_id')} ({u.get('username', 'unknown')})")
        await _async_process_user(u, parsers_map, parsed_cache)
    
    logger.info(f"✅ Cycle completed. Parsed {len(parsed_cache)} unique URLs")



async def async_run_for_user(user_id: str, ignore_window: bool = True):
    """Parse and notify only for a given user immediately.
    ignore_window=True means run regardless of schedule time window.
    """
    now = berlin_now()
    if not ignore_window:
        if now.hour < SCHED_START_HOUR:
            return
        if now.hour > SCHED_END_HOUR or (now.hour == SCHED_END_HOUR and now.minute > 30):
            return

    # Fetch user and filters
    u = um.db.users.find_one({"user_id": str(user_id)})
    if not u:
        return
    uid = str(u["user_id"])
    f = um.get_user_filters(uid) or {"search_urls": [], "preferred_locations": []}
    # Access gate: trial vs subscription
    if not um.has_access(u, f):
        # If trial just expired, send one-time notice with admin contact
        try:
            from datetime import datetime as _dt
            te = f.get("trial_expires_at")
            notified = f.get("trial_expired_notified")
            if f.get("access_mode") == "trial" and te and not notified:
                if _dt.utcnow() > _dt.fromisoformat(te):
                    msg = (
                        "⛔ Безкоштовний тест завершився.\n\n"
                        f"Щоб продовжити отримувати оголошення, напишіть адміну {SUPPORT_CONTACT}."
                    )
                    await send_message(uid, msg)
                    um.db.user_filters.update_one({"user_id": uid}, {"$set": {"trial_expired_notified": True}})
        except Exception:
            pass
        return
    # Access gate: trial vs subscription
    if not um.has_access(u, f):
        return
    urls = f.get("search_urls", [])
    preferred = f.get("preferred_locations", [])

    parsers_map = {
        "kleinanzeigen.de": KleinanzeigenParser(),
        "immowelt.de": ImmoweltParser(),
    }

    parsed_cache: dict[str, list] = {}
    new_found = 0
    per_url_stats: Dict[str, Dict[str, int]] = {}
    for url in urls:
        domain = "" if "//" not in url else url.split("//", 1)[1].split("/", 1)[0]
        parser = None
        for d, p in parsers_map.items():
            if d in domain:
                parser = p
                break
        if not parser:
            continue
        if url in parsed_cache:
            listings = parsed_cache[url]
        else:
            try:
                listings = parser.parse(url)
            except Exception:
                listings = []
            parsed_cache[url] = listings
        per_url_stats[url] = {"parsed": len(listings), "filtered": 0, "dedup": 0, "limit": 0, "sent": 0}
        for lst in listings:
            if not match_location(lst.location, preferred):
                per_url_stats[url]["filtered"] += 1
                continue
            lid = um.record_listing(lst.__dict__)
            key = lst.listing_id or lst.hash
            if um.db.notification_stats.find_one({"recipient_id": uid, "listing_id": key}):
                per_url_stats[url]["dedup"] += 1
                continue
            if not um.can_send_notification(uid):
                per_url_stats[url]["limit"] += 1
                continue
            # Rich message without visiting detail page (same as run_once)
            title = lst.title or "Без назви"
            lines = ["🏠 Знайдено нову квартиру!", f"📝 {title}"]
            if lst.price and lst.price > 0:
                lines.append(f"💰 Цена: {lst.price}€")
            else:
                lines.append("💰 Ціна: за запитом")
            if lst.size:
                lines.append(f"📏 Площа: {lst.size} м²")
            if lst.rooms:
                lines.append(f"🚪 Кімнат: {lst.rooms}")
            if lst.location:
                lines.append(f"📍 Локація: {lst.location}")
            lines.append(f"\n🔗 Переглянути оголошення\n{lst.url}")
            text = "\n".join(lines)
            if await send_message(uid, text):
                um.record_notification(uid, key, "new_listing")
                new_found += 1
                per_url_stats[url]["sent"] += 1
    if not urls:
        return
    if new_found == 0:
        await send_message(uid, "Немає нових квартир за вашими посиланнями")
        um.record_notification(uid, f"none-{datetime.utcnow().isoformat()}", "no_new_listings")
    if DEBUG_STATS and TELEGRAM_ADMIN_CHAT_ID:
        notification_text = _format_admin_notification(uid, u, per_url_stats, new_found)
        await send_message(TELEGRAM_ADMIN_CHAT_ID, notification_text)
    # Start/continue per-user cadence from the moment links were set / first run
    um.mark_user_run(uid)


async def _async_process_user(u: Dict, parsers_map: Dict[str, object], parsed_cache: Dict[str, list]):
    uid = str(u["user_id"])  # might be fallback
    f = um.get_user_filters(uid) or {"search_urls": [], "preferred_locations": []}
    # Access gate: trial vs subscription
    if not um.has_access(u, f):
        # Notify once on trial expiry
        try:
            from datetime import datetime as _dt
            te = f.get("trial_expires_at")
            notified = f.get("trial_expired_notified")
            if f.get("access_mode") == "trial" and te and not notified:
                if _dt.utcnow() > _dt.fromisoformat(te):
                    msg = (
                        "⛔ Безкоштовний тест завершився.\n\n"
                        f"Щоб продовжити отримувати оголошення, напишіть адміну {SUPPORT_CONTACT}."
                    )
                    await send_message(uid, msg)
                    um.db.user_filters.update_one({"user_id": uid}, {"$set": {"trial_expired_notified": True}})
        except Exception:
            pass
        return
    # Access gate: trial vs subscription
    if not um.has_access(u, f):
        return
    urls = f.get("search_urls", [])
    preferred = f.get("preferred_locations", [])
    # cadence gating
    due = True
    try:
        nra = f.get("next_run_at")
        if nra:
            from datetime import datetime as _dt
            nra_dt = _dt.fromisoformat(nra)
            due = _dt.utcnow() >= nra_dt
    except Exception:
        due = True
    if not due:
        return
    if not urls:
        return
    per_url_stats: Dict[str, Dict[str, int]] = {}
    new_found = 0
    for url in urls:
        domain = "" if "//" not in url else url.split("//", 1)[1].split("/", 1)[0]
        parser = None
        for d, p in parsers_map.items():
            if d in domain:
                parser = p
                break
        if not parser:
            continue
        if url in parsed_cache:
            listings = parsed_cache[url]
        else:
            try:
                listings = parser.parse(url)
            except Exception:
                listings = []
            parsed_cache[url] = listings
        per_url_stats[url] = {"parsed": len(listings), "filtered": 0, "dedup": 0, "limit": 0, "sent": 0}
        for lst in listings:
            # Persist listing once for global dedup across users
            try:
                um.record_listing(lst.__dict__)
            except Exception:
                pass
            if not match_location(lst.location, f.get("preferred_locations", [])):
                per_url_stats[url]["filtered"] += 1
                continue
            key = lst.listing_id or lst.hash
            if um.db.notification_stats.find_one({"recipient_id": uid, "listing_id": key}):
                per_url_stats[url]["dedup"] += 1
                continue
            if not um.can_send_notification(uid):
                per_url_stats[url]["limit"] += 1
                continue
            title = lst.title or "Без назви"
            lines = ["🏠 Знайдено нову квартиру!", f"📝 {title}"]
            if lst.price and lst.price > 0:
                lines.append(f"💰 Цена: {lst.price}€")
            else:
                lines.append("💰 Ціна: за запитом")
            if lst.size:
                lines.append(f"📏 Площа: {lst.size} м²")
            if lst.rooms:
                lines.append(f"🚪 Кімнат: {lst.rooms}")
            if lst.location:
                lines.append(f"📍 Локація: {lst.location}")
            lines.append(f"\n🔗 Переглянути оголошення\n{lst.url}")
            text = "\n".join(lines)
            if await send_message(uid, text):
                um.record_notification(uid, key, "new_listing")
                per_url_stats[url]["sent"] += 1
                new_found += 1
    if new_found == 0:
        await send_message(uid, "Немає нових квартир за вашими посиланнями")
        um.record_notification(uid, f"none-{datetime.utcnow().isoformat()}", "no_new_listings")
    elif DEBUG_STATS and TELEGRAM_ADMIN_CHAT_ID:
        notification_text = _format_admin_notification(uid, u, per_url_stats, new_found)
        await send_message(TELEGRAM_ADMIN_CHAT_ID, notification_text)
    um.mark_user_run(uid)


def set_application_for_send(app: Application):
    global application
    application = app

async def schedule_jobs(app: Application):
    logger.info(f"🚀 Scheduler initialized - runs every {NOTIFY_INTERVAL_MINUTES} minutes ({SCHED_START_HOUR}:00-{SCHED_END_HOUR}:30)")
    # Immediate first run (respects daily window)
    await async_run_cycle(ignore_window=False)

    # Align repeating schedule to the next :00 / :30 Berlin minute to avoid drift
    now = berlin_now()
    # Floor to minute
    base = now.replace(second=0, microsecond=0)
    remainder = now.minute % NOTIFY_INTERVAL_MINUTES
    add_min = (NOTIFY_INTERVAL_MINUTES - remainder) if remainder != 0 else NOTIFY_INTERVAL_MINUTES
    next_tick = base.replace(minute=base.minute) + timedelta(minutes=add_min)
    seconds_until_next = max(1, int((next_tick - now).total_seconds()))

    app.job_queue.run_repeating(
        lambda _: asyncio.create_task(async_run_cycle()),
        interval=NOTIFY_INTERVAL_MINUTES * 60,
        first=seconds_until_next,
    )
    logger.info(
        f"⏰ Next run aligned at {next_tick.strftime('%Y-%m-%d %H:%M:%S')} Berlin time (in {seconds_until_next}s)"
    )

__all__ = [
    "async_run_for_user",
    "async_run_cycle",
    "schedule_jobs",
    "set_application_for_send",
]
