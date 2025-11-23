# -*- coding: utf-8 -*-
from typing import Dict, Any, List
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    LinkPreviewOptions,
)
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, SUPPORT_CONTACT
from .user_manager import UserManager
from .runner import async_run_for_user, async_run_cycle
from .translations import get_text, LANGUAGE_NAMES

um = UserManager()

# Track last sent inline menu message per user so we can edit instead of spamming new ones
_user_menu_messages: Dict[str, Dict[str, int]] = {}
_admin_menu_messages: Dict[str, Dict[str, int]] = {}
_reply_kb_set: set[str] = set()  # Users who have received the persistent reply keyboard

async def _ensure_user_menu(context: ContextTypes.DEFAULT_TYPE, uid: str, welcome_text: str):
    """Ensure a single persistent inline menu message exists for user; edit if already sent."""
    try:
        msg_info = _user_menu_messages.get(uid)
        kb = _user_menu_keyboard(uid)
        if msg_info:
            # Try edit existing message text + keyboard
            try:
                await context.bot.edit_message_text(
                    chat_id=msg_info["chat_id"],
                    message_id=msg_info["message_id"],
                    text=welcome_text,
                    reply_markup=kb
                )
                return
            except Exception:
                pass  # Fall through to send new
        sent = await context.bot.send_message(chat_id=uid, text=welcome_text, reply_markup=kb)
        _user_menu_messages[uid] = {"chat_id": sent.chat_id, "message_id": sent.message_id}
    except Exception as e:
        print(f"Failed ensuring user menu for {uid}: {e}")

async def _ensure_admin_menu(context: ContextTypes.DEFAULT_TYPE, uid: str):
    """Ensure single persistent admin menu message exists; edit if possible."""
    try:
        msg_info = _admin_menu_messages.get(uid)
        kb = _admin_menu_keyboard()
        text = "Адмін-меню:"
        if msg_info:
            try:
                await context.bot.edit_message_text(
                    chat_id=msg_info["chat_id"],
                    message_id=msg_info["message_id"],
                    text=text,
                    reply_markup=kb
                )
                return
            except Exception:
                pass
        sent = await context.bot.send_message(chat_id=uid, text=text, reply_markup=kb)
        _admin_menu_messages[uid] = {"chat_id": sent.chat_id, "message_id": sent.message_id}
    except Exception as e:
        print(f"Failed ensuring admin menu for {uid}: {e}")

WELCOME_TEXT = (
    """🏠 Хочеш знайти квартиру в Німеччині швидко та без стресу?

Уяви: нове оголошення з’явилося на Kleinanzeigen або Immowelt — і ти отримуєш повідомлення одразу, ще до того, як його побачать сотні інших людей.

✅ Бот перевіряє сайти автоматично кожні 30 хвилин.
✅ Ти отримуєш повідомлення відразу після появи нового оголошення.
✅ Пиши власникам першим і підвищуй свої шанси знайти квартиру!

🎁 Спробуй безкоштовно 14 днів — переконайся сам!
💶 Після тесту — лише 9€/місяць.

🚀 Натисни «РОЗПОЧАТИ» 👇 і будь серед перших, хто отримує нові оголошення!
"""
)

# Support one or multiple admin IDs (comma-separated)
_admin_ids = set()
if TELEGRAM_ADMIN_CHAT_ID:
    for part in str(TELEGRAM_ADMIN_CHAT_ID).split(","):
        s = part.strip()
        if s:
            _admin_ids.add(s)

def is_admin(user_id: str) -> bool:
    return user_id in _admin_ids


def _language_selection_keyboard():
    """Build language selection keyboard with 3 languages."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("language_ukrainian", "uk"), callback_data="lang_uk")],
        [InlineKeyboardButton(get_text("language_russian", "ru"), callback_data="lang_ru")],
        [InlineKeyboardButton(get_text("language_arabic", "ar"), callback_data="lang_ar")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    uid = str(u.id)
    if is_admin(uid):
        # Ensure admin is recorded as active admin, no pending text
        um.upsert_user(uid, u.username or "", u.first_name or "", u.last_name or "")
        um.db.users.update_one(
            {"user_id": uid},
            {"$set": {"role": "admin", "status": "active", "date_activated": datetime.utcnow().isoformat(), "language": "uk"}},
        )
        await _ensure_admin_menu(context, uid)
        return
    
    # Regular user path: register/update user
    um.upsert_user(uid, u.username or "", u.first_name or "", u.last_name or "")
    
    # Check if user has already selected a language by checking the database directly
    user_doc = um.db.users.find_one({"user_id": uid})
    user_lang = user_doc.get("language") if user_doc else None
    
    if user_lang is None:
        # User hasn't selected a language yet, show language selection
        await update.message.reply_text(
            get_text("select_language", "uk"),
            reply_markup=_language_selection_keyboard()
        )
        # Provide persistent reply keyboard immediately (default Ukrainian label)
        if uid not in _reply_kb_set:
            rk = ReplyKeyboardMarkup([["Меню"]], resize_keyboard=True)
            try:
                await update.message.reply_text("Натисни 'Меню' щоб відкрити панель", reply_markup=rk)
                _reply_kb_set.add(uid)
            except Exception:
                pass
    else:
        # User has already selected a language, show welcome message
        await _ensure_user_menu(context, uid, get_text("welcome_text", user_lang))
        if uid not in _reply_kb_set:
            label = "Меню" if user_lang in ("uk", "ru") else ("القائمة" if user_lang == "ar" else "Menu")
            rk = ReplyKeyboardMarkup([[label]], resize_keyboard=True)
            try:
                await update.message.reply_text(get_text("menu_hint", user_lang), reply_markup=rk)
                _reply_kb_set.add(uid)
            except Exception:
                pass


def _user_menu_keyboard(uid: str | None = None):
    """Build user menu.
    
    Note: "Add more cities" functionality is now available via /add_cities command in Bot Commands Menu.

    - For нового юзера (без активної підписки / триалу) показуємо тільки:
      * "Спробувати 14 днів БЕЗКОШТОВНО"
      * "Техпідтримка"
      * "Змінити мову"
    - Для користувача з активним триалом або підпискою показуємо:
      * "Дата початку підписки"
      * "Техпідтримка"
      * "Змінити мову"
    """
    rows = []
    has_active_sub = False
    user_lang = "uk"  # Default language
    
    if uid is not None:
        u = um.db.users.find_one({"user_id": uid}) or {}
        user_lang = u.get("language", "uk")
        
        # Determine if user already має активний доступ (trial або підписка)
        from datetime import datetime as _dt
        now_iso = _dt.utcnow().isoformat()

        # Check paid subscription
        sub_expires = u.get("subscription_expires")
        if sub_expires:
            try:
                has_active_sub = _dt.fromisoformat(sub_expires) >= _dt.fromisoformat(now_iso)
            except Exception:
                has_active_sub = False

        # Check trial in filters
        f = um.db.user_filters.find_one({"user_id": uid}) or {}
        trial_expires = f.get("trial_expires_at")
        if trial_expires and not has_active_sub:
            try:
                has_active_sub = _dt.fromisoformat(trial_expires) >= _dt.fromisoformat(now_iso)
            except Exception:
                pass

    # Show "Try free" button only if user doesn't have active subscription
    if not has_active_sub:
        rows.append([InlineKeyboardButton(get_text("btn_start_free", user_lang), callback_data="user_subscribe")])
    
    # Show subscription info button if user has active subscription
    if has_active_sub:
        rows.append([InlineKeyboardButton(get_text("btn_subscription_date", user_lang), callback_data="user_sub_info")])
    
    # Show "Add more cities" button always so user can update or submit search params
    rows.append([InlineKeyboardButton(get_text("btn_add_cities", user_lang), callback_data="user_add_cities")])
    
    # Support button always visible
    rows.append([InlineKeyboardButton(get_text("btn_support", user_lang), callback_data="user_support")])
    
    # Language change button
    rows.append([InlineKeyboardButton(get_text("btn_change_language", user_lang), callback_data="user_change_lang")])

    return InlineKeyboardMarkup(rows)


def _back_to_menu_keyboard(lang: str = "uk"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(get_text("btn_back_menu", lang), callback_data="user_back_menu")]])


async def _send_setup_complete_notification(
    context: ContextTypes.DEFAULT_TYPE,
    target_id: str,
    target_lang: str,
    skip_welcome: bool = False,
):
    """Notify user that parsing/search has been configured.

    Always sends the "setup_configured" message.
    Optionally (when skip_welcome == False) sends the long marketing welcome text.

    This allows suppressing the large onboarding message for cases where an
    admin simply призначає / оновлює посилання (assigns links) for an already
    active user, so the user does not keep receiving the big promo block.
    """
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=get_text("setup_configured", target_lang)
        )
        if not skip_welcome:
            await _ensure_user_menu(context, target_id, get_text("welcome_text", target_lang))
        else:
            await _ensure_user_menu(context, target_id, "✅ Пошук оновлено.")
    except Exception as e:
        print(f"Failed to send setup notification to user {target_id}: {e}")


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /approve <user_id>
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    if not context.args:
        await update.message.reply_text("Використання: /approve <user_id>")
        return
    user_id = context.args[0]
    um.approve_user(user_id)
    await update.message.reply_text(f"Користувача {user_id} активовано на 30 днів.")

async def set_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /set_location <user_id> <comma-separated links> | optional: ; cities=City1,City2
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    if not context.args:
        await update.message.reply_text("Використання: /set_location <user_id> <посилання через кому> ; cities=Місто1,Місто2")
        return
    text = " ".join(context.args)
    parts = text.split(";")
    user_and_links = parts[0].strip()
    cities = []
    if len(parts) > 1:
        for p in parts[1:]:
            if p.strip().lower().startswith("cities="):
                cities = [c.strip() for c in p.split("=", 1)[1].split(",") if c.strip()]
    first_space = user_and_links.find(" ")
    if first_space == -1:
        await update.message.reply_text("Потрібно вказати user_id і посилання.")
        return
    user_id = user_and_links[:first_space].strip()
    links_part = user_and_links[first_space+1:].strip()
    # Robust URL extraction: find all http/https links, don't split by comma
    import re as _re
    links = _re.findall(r"https?://\S+", links_part)
    um.set_user_links(user_id, links, cities)
    await update.message.reply_text(f"Оновлено посилання для {user_id}. Міста: {', '.join(cities) if cities else '—'}")
    # Trigger immediate async parsing for this user
    if context.application:
        context.application.create_task(async_run_for_user(user_id, ignore_window=True))

async def view_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /view_location <user_id>
    # Admins can view any user; users can view only self if provide their id
    if not context.args:
        await update.message.reply_text("Використання: /view_location <user_id>")
        return
    user_id = context.args[0]
    f = um.get_user_filters(user_id)
    if not f:
        await update.message.reply_text("Фільтри не знайдені.")
        return
    await update.message.reply_text(
        "Посилання:\n- " + "\n- ".join(f.get("search_urls", [])) +
        "\nМіста: " + ", ".join(f.get("preferred_locations", []))
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if is_admin(uid):
        await update.message.reply_text(
            "🔧 Команди адміністратора:\n\n"
            "📋 Основні команди:\n"
            "/start — почати роботу з ботом\n"
            "/admin — відкрити адмін-меню\n"
            "/users — список користувачів та посилань\n"
            "/help — показати цю довідку\n\n"
            "➕ Додавання посилань (найпростіші способи):\n"
            "/add_link <user_id або @username> <посилання...> — ШВИДКЕ додавання посилань\n"
            "/assign_links <user_id або @username> <посилання...> — те саме що /add_link\n"
            "/reply_assign — відповісти Reply на повідомлення з посиланнями для призначення\n\n"
            "👥 Управління користувачами:\n"
            "/approve <user_id> — схвалити користувача\n"
            "/delete_user <user_id> — видалити користувача\n"
            "/view_location <user_id> — переглянути міста/посилання користувача\n\n"
            "⚙️ Налаштування:\n"
            "/set_location <user_id> <посилання...> ; cities=Місто1,Місто2 — детальне налаштування\n"
            "/set_links <url1 url2 ...> — задати посилання собі\n\n"
            "🚀 Інше:\n"
            "/test_run — тестовий запуск парсингу\n"
            "/broadcast <текст> — розсилка повідомлення всім користувачам\n\n"
            "💡 Підказка: для швидкого додавання посилань просто використайте /add_link або /reply_assign!\n"
        )
    else:
        await update.message.reply_text(
            "Команди користувача:\n/start — показати меню та кнопки.\n"
            "Використовуйте кнопки для підтримки та перегляду дати старту підписки."
        )


async def support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: /support — show support contact."""
    print("/support command received from", update.effective_user.id)
    contact = SUPPORT_CONTACT or "@admin"
    try:
        await update.message.reply_text(
            f"🛠️ Техпідтримка\n\nЗв'яжіться з адміністратором: {contact}",
            reply_markup=_back_to_menu_keyboard(),
        )
    except Exception:
        import traceback; print("Error in /support:", traceback.format_exc())


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: /status — show subscription start/end dates or state."""
    print("/status command received from", update.effective_user.id)
    uid = str(update.effective_user.id)
    u = um.db.users.find_one({"user_id": uid})
    status = (u or {}).get("status")
    date_activated = (u or {}).get("date_activated")
    subscription_expires = (u or {}).get("subscription_expires")
    requested = (u or {}).get("requested_subscription")
    now_iso = datetime.utcnow().isoformat()
    active_valid = (
        status == "active" and subscription_expires and subscription_expires >= now_iso
    )
    # Format as DD.MM.YYYY
    def _fmt_date(iso: str) -> str:
        try:
            from datetime import datetime as _dt
            return _dt.fromisoformat(iso).strftime("%d.%m.%Y")
        except Exception:
            return iso
    if active_valid and subscription_expires:
        msg = f"📅 Підписка активна до: {_fmt_date(subscription_expires)}"
    elif requested:
        msg = "⏳ Заявка на підписку очікує підтвердження адміністратора."
    else:
        msg = "❌ Ви ще не активовані."
    try:
        await update.message.reply_text(msg, reply_markup=_back_to_menu_keyboard())
    except Exception:
        import traceback; print("Error in /status:", traceback.format_exc())


async def add_cities_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: /add_cities — start the add cities setup flow."""
    print("/add_cities command received from", update.effective_user.id)
    uid = str(update.effective_user.id)
    
    try:
        # Get user's language
        user_lang = um.get_user_language(uid)
        
        # Show warning about overwriting parameters
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text("btn_back_menu", user_lang), callback_data="user_setup_cancel")]])
        await update.message.reply_text(
            get_text("setup_add_cities_warning", user_lang),
            reply_markup=cancel_kb
        )
        
        # Start setup conversation - ask for city
        await update.message.reply_text(
            get_text("setup_ask_city", user_lang),
            reply_markup=cancel_kb
        )
        
        # Store language in context for conversation
        context.user_data["setup_user_lang"] = user_lang
        context.user_data["setup_user_id"] = uid
        context.user_data["setup_from_menu"] = True  # Mark that this request is from menu
        
        return USER_SETUP_ASK_CITY
        
    except Exception as e:
        print(f"Error starting add cities for {uid}: {e}")
        import traceback
        traceback.print_exc()
        return ConversationHandler.END


async def assign_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick command to assign links to a user with mode selection.
    Usage: /assign_links <user_id_or_username> <url1> <url2> ...
    Admin will be asked to choose between trial and subscription mode.
    """
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Використання: /assign_links <user_id або @username> <посилання...>\n\n"
            "Приклад:\n"
            "/assign_links 123456789 https://kleinanzeigen.de/... https://immowelt.de/...\n"
            "/assign_links @username https://kleinanzeigen.de/..."
        )
        return
    
    # Extract user identifier and links
    user_identifier = context.args[0].lstrip("@")
    links_str = " ".join(context.args[1:]).strip()
    
    import re as _re
    links = _re.findall(r"https?://\S+", links_str)
    
    if not links:
        await update.message.reply_text("❌ Не знайдено жодного посилання. Переконайтеся, що ви вказали URL.")
        return
    
    # Find user by ID or username
    user_doc = None
    if user_identifier.isdigit():
        user_doc = um.db.users.find_one({"user_id": user_identifier})
    else:
        user_doc = um.db.users.find_one({"username": {"$regex": f"^{user_identifier}$", "$options": "i"}})
    
    if not user_doc:
        await update.message.reply_text(
            f"❌ Користувача '{user_identifier}' не знайдено.\n\n"
            "Переконайтеся, що користувач вже взаємодіяв з ботом хоча б раз."
        )
        return
    
    target_id = user_doc["user_id"]
    label = user_doc.get("username") or user_doc.get("first_name") or target_id
    
    # Store data in context for the callback
    context.user_data["quick_assign_target_id"] = target_id
    context.user_data["quick_assign_links"] = links
    context.user_data["quick_assign_label"] = label
    
    # Ask admin to choose mode
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧪 Тест (14 днів)", callback_data="quick_assign_trial"),
            InlineKeyboardButton("💳 Підписка (30 днів)", callback_data="quick_assign_subscription")
        ],
        [InlineKeyboardButton("❌ Скасувати", callback_data="quick_assign_cancel")]
    ])
    
    links_preview = "\n".join([f"• {url}" for url in links[:5]])
    if len(links) > 5:
        links_preview += f"\n... та ще {len(links) - 5} посилань"
    
    await update.message.reply_text(
        f"📋 Призначення посилань для користувача:\n"
        f"👤 {label} (ID: {target_id})\n\n"
        f"📎 Посилання ({len(links)}):\n{links_preview}\n\n"
        f"Оберіть режим доступу:",
        reply_markup=kb
    )


async def reply_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Assign links from a user's message by replying to it.
    Admin replies to user's message containing links with /reply_assign command.
    """
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Ця команда працює тільки як відповідь (Reply) на повідомлення користувача.\n\n"
            "Щоб використати:\n"
            "1. Знайдіть повідомлення користувача з посиланнями\n"
            "2. Натисніть Reply на те повідомлення\n"
            "3. Напишіть /reply_assign"
        )
        return
    
    replied_msg = update.message.reply_to_message
    target_user = replied_msg.from_user
    
    if not target_user:
        await update.message.reply_text("❌ Не вдалося визначити користувача з повідомлення.")
        return
    
    target_id = str(target_user.id)
    
    # Extract links from the replied message
    import re as _re
    links = _re.findall(r"https?://\S+", replied_msg.text or "")
    
    if not links:
        await update.message.reply_text(
            "❌ У повідомленні не знайдено посилань.\n\n"
            "Переконайтеся, що повідомлення містить URL (https://...)."
        )
        return
    
    # Ensure user exists in database
    user_doc = um.db.users.find_one({"user_id": target_id})
    if not user_doc:
        # Create user record
        um.upsert_user(target_id, target_user.username or "", target_user.first_name or "", target_user.last_name or "")
        user_doc = um.db.users.find_one({"user_id": target_id})
    
    label = user_doc.get("username") or user_doc.get("first_name") or target_id
    
    # Store data in context for the callback
    context.user_data["quick_assign_target_id"] = target_id
    context.user_data["quick_assign_links"] = links
    context.user_data["quick_assign_label"] = label
    
    # Ask admin to choose mode
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧪 Тест (14 днів)", callback_data="quick_assign_trial"),
            InlineKeyboardButton("💳 Підписка (30 днів)", callback_data="quick_assign_subscription")
        ],
        [InlineKeyboardButton("❌ Скасувати", callback_data="quick_assign_cancel")]
    ])
    
    links_preview = "\n".join([f"• {url}" for url in links[:5]])
    if len(links) > 5:
        links_preview += f"\n... та ще {len(links) - 5} посилань"
    
    await update.message.reply_text(
        f"📋 Призначення посилань для користувача:\n"
        f"👤 {label} (ID: {target_id})\n\n"
        f"📎 Посилання ({len(links)}):\n{links_preview}\n\n"
        f"Оберіть режим доступу:",
        reply_markup=kb
    )


async def set_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin helper to set links for yourself quickly
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    if not context.args:
        await update.message.reply_text("Використання: /set_links <url1,url2,...>")
        return
    links_str = " ".join(context.args).strip()
    import re as _re
    links = _re.findall(r"https?://\S+", links_str)
    um.set_user_links(caller_id, links, [])
    await update.message.reply_text("Посилання оновлено для адміністратора.")


async def test_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    if context.application:
        context.application.create_task(async_run_cycle(ignore_window=True))
    await update.message.reply_text("Тестовий асинхронний запуск заплановано.")


async def force_run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    if not context.args:
        await update.message.reply_text("Використання: /force_run <user_id>")
        return
    target = context.args[0]
    if context.application:
        context.application.create_task(async_run_for_user(target, ignore_window=True))
    await update.message.reply_text(f"Примусовий запуск для {target} заплановано.")


async def refresh_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: force refresh bot commands in Telegram.
    Usage: /refresh_commands
    """
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    
    try:
        # Delete all commands first
        await context.bot.delete_my_commands()
        
        # Set default (non-admin) commands - only 3 main commands
        await context.bot.set_my_commands(
            [
                BotCommand("start", "Почати"),
                BotCommand("status", "Статус підписки"),
                BotCommand("support", "Техпідтримка"),
            ],
            scope=BotCommandScopeDefault(),
        )
        
        # Set admin commands for each admin
        for aid in _admin_ids:
            await context.bot.set_my_commands(
                [
                    BotCommand("start", "Почати (адмін)"),
                    BotCommand("admin", "Відкрити адмін-меню"),
                    BotCommand("users", "Список користувачів та посилань"),
                    BotCommand("add_link", "Швидко додати посилання користувачу"),
                    BotCommand("assign_links", "Призначити посилання користувачу"),
                    BotCommand("reply_assign", "Призначити посилання відповіддю на повідомлення"),
                    BotCommand("approve", "Схвалити користувача"),
                    BotCommand("set_location", "Призначити міста/посилання"),
                    BotCommand("view_location", "Переглянути міста/посилання"),
                    BotCommand("delete_user", "Видалити користувача"),
                    BotCommand("set_links", "Задати посилання собі"),
                    BotCommand("test_run", "Тестовий запуск парсингу"),
                    BotCommand("broadcast", "Розсилка повідомлення всім"),
                    BotCommand("refresh_commands", "Оновити команди бота"),
                    BotCommand("support", "Техпідтримка"),
                    BotCommand("status", "Статус підписки"),
                    BotCommand("help", "Список адмін-команд"),
                ],
                scope=BotCommandScopeChat(int(aid)),
            )
        
        await update.message.reply_text(
            "✅ Команди бота оновлено!\n\n"
            "Для користувачів (3 команди):\n"
            "• /start - Почати роботу\n"
            "• /status - Статус підписки\n"
            "• /support - Техпідтримка\n\n"
            "Додавання міст доступне через inline-кнопку в меню бота.\n"
            "Користувачам може знадобитися перезапустити бота або натиснути '/' в чаті."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка оновлення команд: {e}")
        import traceback
        traceback.print_exc()


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: broadcast message to all users (except banned).
    Usage: /broadcast <message text>
    """
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    if not context.args:
        await update.message.reply_text("Використання: /broadcast <текст повідомлення>")
        return
    
    message_text = " ".join(context.args)
    users = um.get_all_users_for_broadcast()
    
    if not users:
        await update.message.reply_text("Немає користувачів для розсилки.")
        return
    
    await update.message.reply_text(f"Починаю розсилку для {len(users)} користувачів...")
    
    success_count = 0
    fail_count = 0
    
    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        try:
            await context.bot.send_message(chat_id=user_id, text=message_text)
            success_count += 1
        except Exception as e:
            fail_count += 1
            # Optionally log the error
            print(f"Failed to send to {user_id}: {e}")
    
    await update.message.reply_text(
        f"✅ Розсилка завершена!\n"
        f"Успішно: {success_count}\n"
        f"Помилок: {fail_count}"
    )


async def _post_init(app: Application):
    # Set default (non-admin) commands - only 3 main commands that users actually see
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Почати"),
                BotCommand("status", "Статус підписки"),
                BotCommand("support", "Техпідтримка"),
            ],
            scope=BotCommandScopeDefault(),
        )
    except Exception as e:
        print(f"Error setting user commands: {e}")
        import traceback
        traceback.print_exc()
    # Set admin-specific commands per admin chat
    for aid in _admin_ids:
        try:
            await app.bot.set_my_commands(
                [
                    BotCommand("start", "Почати (адмін)"),
                    BotCommand("admin", "Відкрити адмін-меню"),
                    BotCommand("users", "Список користувачів та посилань"),
                    BotCommand("add_link", "Швидко додати посилання користувачу"),
                    BotCommand("assign_links", "Призначити посилання користувачу"),
                    BotCommand("reply_assign", "Призначити посилання відповіддю на повідомлення"),
                    BotCommand("approve", "Схвалити користувача"),
                    BotCommand("set_location", "Призначити міста/посилання"),
                    BotCommand("view_location", "Переглянути міста/посилання"),
                    BotCommand("delete_user", "Видалити користувача"),
                    BotCommand("set_links", "Задати посилання собі"),
                    BotCommand("test_run", "Тестовий запуск парсингу"),
                    BotCommand("broadcast", "Розсилка повідомлення всім"),
                    BotCommand("support", "Техпідтримка"),
                    BotCommand("status", "Статус підписки"),
                    BotCommand("help", "Список адмін-команд"),
                ],
                scope=BotCommandScopeChat(int(aid)),
            )
        except Exception as e:
            print(f"Error setting admin commands for {aid}: {e}")
            import traceback
            traceback.print_exc()


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to open users overview list with pagination and details."""
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    # Build and send first overview page
    try:
        # Reuse internal builder by calling the same DB queries here
        criteria = {"role": {"$ne": "admin"}}
        total = um.db.users.count_documents(criteria)
        cursor = (
            um.db.users.find(criteria, {"user_id": 1, "username": 1, "first_name": 1, "status": 1, "subscription_expires": 1, "date_added": 1})
            .sort("date_added", -1)
            .limit(PAGE_SIZE)
        )
        users = list(cursor)
        rows: List[List[InlineKeyboardButton]] = []
        def _status_emoji(u: Dict[str, Any]) -> str:
            s = u.get("status")
            if s == "active":
                return "✅"
            if s == "pending":
                return "⏳"
            if s == "banned":
                return "⛔"
            return "⚪"
        for u in users:
            label_base = u.get("username") or u.get("first_name") or u.get("user_id")
            label = f"{_status_emoji(u)} {label_base} ({u.get('user_id')})"
            rows.append([
                InlineKeyboardButton("ℹ️ Деталі", callback_data=f"user_info:{u.get('user_id')}"),
                InlineKeyboardButton(label, callback_data=f"noop:{u.get('user_id')}")
            ])
        nav: List[InlineKeyboardButton] = []
        if total > PAGE_SIZE:
            nav.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"admin_users_page:1"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        text = (
            "Список користувачів (перегляд деталей/посилань).\n"
            f"Сторінка 1, усього користувачів: {total}"
        )
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))
    except Exception as e:
        await update.message.reply_text(f"Помилка: {e}")


# ---- User Setup Request Conversation ----
async def user_setup_city_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle city input from user."""
    city = (update.message.text or "").strip()
    user_lang = context.user_data.get("setup_user_lang", "uk")
    
    if not city:
        await update.message.reply_text(get_text("setup_ask_city", user_lang))
        return USER_SETUP_ASK_CITY
    
    # Store city
    context.user_data["setup_city"] = city
    
    # Ask for price
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text("btn_back_menu", user_lang), callback_data="user_setup_cancel")]])
    await update.message.reply_text(
        get_text("setup_ask_price", user_lang),
        reply_markup=cancel_kb
    )
    
    return USER_SETUP_ASK_PRICE


async def user_setup_price_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle price input from user."""
    price = (update.message.text or "").strip()
    user_lang = context.user_data.get("setup_user_lang", "uk")
    
    if not price:
        await update.message.reply_text(get_text("setup_ask_price", user_lang))
        return USER_SETUP_ASK_PRICE
    
    # Store price
    context.user_data["setup_price"] = price
    
    # Ask for rooms
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text("btn_back_menu", user_lang), callback_data="user_setup_cancel")]])
    await update.message.reply_text(
        get_text("setup_ask_rooms", user_lang),
        reply_markup=cancel_kb
    )
    
    return USER_SETUP_ASK_ROOMS


async def user_setup_rooms_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle rooms input from user and send setup request to admin."""
    rooms = (update.message.text or "").strip()
    user_lang = context.user_data.get("setup_user_lang", "uk")
    uid = context.user_data.get("setup_user_id")
    
    if not rooms:
        await update.message.reply_text(get_text("setup_ask_rooms", user_lang))
        return USER_SETUP_ASK_ROOMS
    
    # Store rooms
    context.user_data["setup_rooms"] = rooms
    
    # Get all setup data
    city = context.user_data.get("setup_city", "—")
    price = context.user_data.get("setup_price", "—")
    from_menu = context.user_data.get("setup_from_menu", False)
    
    # Store setup request in database
    um.db.users.update_one(
        {"user_id": uid},
        {"$set": {
            "setup_request": {
                "city": city,
                "price": price,
                "rooms": rooms,
                "requested_at": datetime.utcnow().isoformat(),
                "from_menu": from_menu
            }
        }}
    )
    
    # Send confirmation to user
    await update.message.reply_text(
        get_text("setup_request_sent", user_lang, city=city, price=price, rooms=rooms),
        reply_markup=_back_to_menu_keyboard(user_lang)
    )
    
    # Send notification to admins with inline buttons
    if _admin_ids:
        u = update.effective_user
        username = f"@{u.username}" if u.username else u.first_name or "—"
        
        # Choose appropriate message based on source
        admin_msg_key = "admin_setup_request_from_menu" if from_menu else "admin_setup_request"
        
        admin_text = get_text(
            admin_msg_key,
            "uk",  # Admin messages in Ukrainian
            username=username,
            user_id=uid,
            city=city,
            price=price,
            rooms=rooms
        )
        
        # Add inline button for quick link assignment
        admin_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Додати посилання", callback_data=f"admin_quick_add_links:{uid}")],
        ])
        
        for aid in _admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=aid, 
                    text=admin_text,
                    reply_markup=admin_kb
                )
            except Exception as e:
                print(f"Failed to notify admin {aid}: {e}")
    
    # Clear context
    context.user_data.pop("setup_user_lang", None)
    context.user_data.pop("setup_user_id", None)
    context.user_data.pop("setup_city", None)
    context.user_data.pop("setup_price", None)
    context.user_data.pop("setup_rooms", None)
    context.user_data.pop("setup_from_menu", None)
    
    return ConversationHandler.END


async def user_setup_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancellation of setup request."""
    query = update.callback_query
    await query.answer()
    
    uid = str(query.from_user.id)
    user_lang = um.get_user_language(uid)
    
    # Clear context
    context.user_data.pop("setup_user_lang", None)
    context.user_data.pop("setup_user_id", None)
    context.user_data.pop("setup_city", None)
    context.user_data.pop("setup_price", None)
    context.user_data.pop("setup_rooms", None)
    context.user_data.pop("setup_from_menu", None)
    
    # Return to menu
    welcome_text = get_text("welcome_text", user_lang)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=welcome_text,
        reply_markup=_user_menu_keyboard(uid)
    )
    
    return ConversationHandler.END


def _admin_quick_add_links_conv() -> ConversationHandler:
    """Build the admin quick add links conversation handler.
    Handles the flow when admin clicks 'Add links' button from setup request notification.
    """
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_quick_add_links_cb, pattern=r"^admin_quick_add_links:")
        ],
        states={
            QUICK_ADD_CHOOSE_MODE: [
                CallbackQueryHandler(admin_quick_add_mode_cb, pattern=r"^quick_add_mode_(trial|subscription)$"),
                CallbackQueryHandler(admin_quick_add_mode_cb, pattern=r"^quick_add_cancel$")
            ],
            QUICK_ADD_ENTER_LINKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_quick_add_enter_links_msg),
                CallbackQueryHandler(admin_quick_add_mode_cb, pattern=r"^quick_add_cancel$")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(admin_quick_add_mode_cb, pattern=r"^quick_add_cancel$")
        ],
        allow_reentry=True,
    )


def _user_setup_conv() -> ConversationHandler:
    """Build the user setup request conversation handler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(user_subscribe_cb, pattern=r"^user_subscribe$"),
            CallbackQueryHandler(user_add_cities_cb, pattern=r"^user_add_cities$"),
            CommandHandler("add_cities", add_cities_cmd)
        ],
        states={
            USER_SETUP_ASK_CITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_setup_city_msg),
                CallbackQueryHandler(user_setup_cancel_cb, pattern=r"^user_setup_cancel$")
            ],
            USER_SETUP_ASK_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_setup_price_msg),
                CallbackQueryHandler(user_setup_cancel_cb, pattern=r"^user_setup_cancel$")
            ],
            USER_SETUP_ASK_ROOMS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_setup_rooms_msg),
                CallbackQueryHandler(user_setup_cancel_cb, pattern=r"^user_setup_cancel$")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(user_setup_cancel_cb, pattern=r"^user_setup_cancel$")
        ],
        allow_reentry=True,
    )


def build_app():
    from telegram.ext import JobQueue
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).job_queue(JobQueue()).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("support", support_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("delete_user", delete_user))
    app.add_handler(CommandHandler("set_location", set_location))
    app.add_handler(CommandHandler("view_location", view_location))
    app.add_handler(CommandHandler("assign_links", assign_links))
    app.add_handler(CommandHandler("add_link", assign_links))  # Alias for easier use
    app.add_handler(CommandHandler("reply_assign", reply_assign))
    app.add_handler(CommandHandler("set_links", set_links))
    app.add_handler(CommandHandler("test_run", test_run))
    app.add_handler(CommandHandler("force_run", force_run_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("refresh_commands", refresh_commands))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("push_menu", push_menu_cmd))
    # Reply keyboard single-button 'Menu' text handler (must be before generic text consumers)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text_handler))
    
    # User menu callbacks - MUST be registered BEFORE ConversationHandler to avoid being captured
    # NOTE: user_subscribe_cb and user_add_cities_cb are handled by user setup conversation, so NOT registered here
    app.add_handler(CallbackQueryHandler(language_selection_cb, pattern=r"^lang_(uk|ru|ar)$"))
    app.add_handler(CallbackQueryHandler(user_change_lang_cb, pattern=r"^user_change_lang$"))
    app.add_handler(CallbackQueryHandler(user_support_cb, pattern=r"^user_support$"))
    app.add_handler(CallbackQueryHandler(user_sub_info_cb, pattern=r"^user_sub_info$"))
    app.add_handler(CallbackQueryHandler(user_back_menu_cb, pattern=r"^user_back_menu$"))
    
    # Admin inline approve/decline from user subscribe request
    app.add_handler(CallbackQueryHandler(admin_inline_approve_cb, pattern=r"^admin_inline_approve:"))
    app.add_handler(CallbackQueryHandler(admin_inline_decline_cb, pattern=r"^admin_inline_decline:"))
    
    # Quick assign callbacks for new /assign_links and /reply_assign commands
    app.add_handler(CallbackQueryHandler(quick_assign_mode_cb, pattern=r"^quick_assign_(trial|subscription|cancel)$"))
    
    # Quick add links conversation from setup request notification
    app.add_handler(_admin_quick_add_links_conv())
    
    # User setup request conversation - MUST come before other callback handlers that might conflict
    app.add_handler(_user_setup_conv())
    
    # Admin inline menu conversation - comes AFTER user callbacks
    app.add_handler(_admin_menu_conv())
    # Global admin handlers enabled so inline admin menu from /start works outside the conversation
    register_global_admin_handlers(app)
    
    return app


# ---- Admin Inline Menu Conversation ----
# Added BROADCAST_ENTER state for admin broadcast flow and CHOOSE_USER_PAID for payment confirmation
# Added QUICK_ADD_CHOOSE_MODE and QUICK_ADD_ENTER_LINKS for quick link assignment from setup request
ADMIN_MENU, CHOOSE_USER, CHOOSE_MODE, ENTER_LINKS, CONFIRM_DELETE, BROADCAST_ENTER, CHOOSE_USER_PAID, QUICK_ADD_CHOOSE_MODE, QUICK_ADD_ENTER_LINKS = range(9)

# User setup request conversation states
USER_SETUP_ASK_CITY, USER_SETUP_ASK_PRICE, USER_SETUP_ASK_ROOMS = range(9, 12)

# Pagination size for admin user list
PAGE_SIZE = 10


def _admin_menu_keyboard():
    kb = [
        [InlineKeyboardButton("👥 Користувачі та посилання", callback_data="admin_users")],
        [InlineKeyboardButton("🔔 Користувачі без активації", callback_data="admin_not_activated")],
        [InlineKeyboardButton("➕ Додати посилання користувачу", callback_data="admin_add_links")],
        [InlineKeyboardButton("💳 Підтвердити оплату", callback_data="admin_paid")],
        [InlineKeyboardButton("❎ Скасувати підписку", callback_data="admin_cancel_sub")],
        [InlineKeyboardButton("📣 Розсилка повідомлення", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🗑 Видалити користувача", callback_data="admin_delete")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")],
    ]
    return InlineKeyboardMarkup(kb)


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        await update.message.reply_text("Лише адміністратор може відкривати меню.")
        return ConversationHandler.END
    await update.message.reply_text("Адмін-меню:", reply_markup=_admin_menu_keyboard())
    return ADMIN_MENU


async def admin_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    if data == "admin_users":
        # Show paginated users overview (page 0)
        await _show_users_overview_page(query, page=0)
        return ADMIN_MENU
    elif data == "admin_not_activated":
        # Show users who started bot but didn't activate subscription
        users = um.get_users_started_but_not_activated()
        if not users:
            await query.edit_message_text(
                "✅ Немає користувачів, які стартували бота, але не активували підписку.\n\n"
                "Всі користувачі або активували підписку, або ще не стартували бота.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu_back")]])
            )
            return ADMIN_MENU
        
        # Format user list
        text_lines = [
            "🔔 Користувачі, які стартували бота, але не активували підписку:\n",
            f"Всього: {len(users)}\n"
        ]
        
        from datetime import datetime as _dt
        for u in users[:20]:  # Show first 20
            uid = u.get("user_id")
            username = u.get("username", "")
            first_name = u.get("first_name", "")
            bot_started_at = u.get("bot_started_at", "")
            
            label = f"@{username}" if username else first_name or uid
            try:
                started_date = _dt.fromisoformat(bot_started_at).strftime("%d.%m.%Y")
            except Exception:
                started_date = "—"
            
            text_lines.append(f"• {label} (ID: {uid}) - старт: {started_date}")
        
        if len(users) > 20:
            text_lines.append(f"\n... та ще {len(users) - 20} користувачів")
        
        text_lines.append(
            "\n💡 Використайте /broadcast для надсилання повідомлення всім користувачам "
            "або додайте посилання окремим користувачам."
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📣 Розсилка цим користувачам", callback_data="admin_broadcast_not_activated")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu_back")]
        ])
        await query.edit_message_text("\n".join(text_lines), reply_markup=kb)
        return ADMIN_MENU
    if data == "admin_add_links":
        # Show paginated list of users for selection (page 0)
        await _show_users_page(query, page=0)
        # Ensure search mode is off by default
        context.user_data.pop("awaiting_user_search", None)
        return CHOOSE_USER
    elif data == "admin_broadcast":
        # Ask admin to enter the broadcast message text
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
        await query.edit_message_text(
            "Надішліть текст повідомлення для розсилки всім користувачам.",
            reply_markup=kb,
        )
        return BROADCAST_ENTER
    elif data == "admin_cancel_sub":
        # List users with an active subscription
        now_iso = datetime.utcnow().isoformat()
        criteria = {
            "status": "active",
            "subscription_expires": {"$gt": now_iso},
        }
        users = list(um.db.users.find(criteria, {"user_id": 1, "username": 1, "first_name": 1}).limit(25))
        if not users:
            await query.edit_message_text("Немає користувачів з активною підпискою.")
            return ConversationHandler.END
        rows = []
        for u in users:
            label = u.get("username") or u.get("first_name") or u.get("user_id")
            rows.append([InlineKeyboardButton(f"Скасувати: {label} ({u['user_id']})", callback_data=f"cancel_sub:{u['user_id']}")])
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        await query.edit_message_text("Оберіть користувача для скасування підписки:", reply_markup=InlineKeyboardMarkup(rows))
        return CHOOSE_USER
    elif data == "admin_paid":
        # List users awaiting payment or without active subscription
        now_iso = datetime.utcnow().isoformat()
        criteria = {
            "$or": [
                {"awaiting_payment": True},
                {"subscription_expires": None},
                {"subscription_expires": {"$lt": now_iso}},
            ],
            "status": {"$ne": "banned"},
        }
        users = list(um.db.users.find(criteria, {"user_id": 1, "username": 1, "first_name": 1}).limit(20))
        if not users:
            await query.edit_message_text("Немає користувачів, які очікують оплати.")
            return ConversationHandler.END
        rows = []
        for u in users:
            label = u.get("username") or u.get("first_name") or u.get("user_id")
            rows.append([InlineKeyboardButton(f"Оплата: {label} ({u['user_id']})", callback_data=f"mark_paid:{u['user_id']}")])
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        await query.edit_message_text("Оберіть користувача для активації підписки (оплата отримана):", reply_markup=InlineKeyboardMarkup(rows))
        return CHOOSE_USER_PAID
    elif data == "admin_delete":
        # Show delete users page with search option
        await _show_delete_users_page(query, page=0)
        # Ensure search mode is off by default
        context.user_data.pop("awaiting_user_delete_search", None)
        return CONFIRM_DELETE
    elif data == "admin_cancel":
        await query.edit_message_text("Скасовано.")
        return ConversationHandler.END
    else:
        await query.edit_message_text("Невідома дія.")
        return ConversationHandler.END


async def pick_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("pick_user:"):
        await query.edit_message_text("Помилка вибору користувача.")
        return ConversationHandler.END
    target_id = data.split(":", 1)[1]
    context.user_data["target_user_id"] = target_id
    # Ask for assignment mode: trial vs subscription
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Тест (14 днів)", callback_data="mode_trial"), InlineKeyboardButton("💳 Підписка (30 днів)", callback_data="mode_subscription")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")],
    ])
    await query.edit_message_text(
        f"Користувача {target_id} обрано. Оберіть режим призначення посилань:",
        reply_markup=kb,
    )
    return CHOOSE_MODE


async def _show_users_page(query, page: int):
    """Render a page with users for admin selection."""
    try:
        # Exclude admins from the list
        criteria = {"role": {"$ne": "admin"}}
        total = um.db.users.count_documents(criteria)
        skip = max(0, page) * PAGE_SIZE
        cursor = (
            um.db.users.find(criteria, {"user_id": 1, "username": 1, "first_name": 1, "status": 1, "subscription_expires": 1, "date_added": 1})
            .sort("date_added", -1)
            .skip(skip)
            .limit(PAGE_SIZE)
        )
        users = list(cursor)
        rows: List[List[InlineKeyboardButton]] = []
        # Map status to icons for quick scan
        def _status_emoji(u: Dict[str, Any]) -> str:
            s = u.get("status")
            if s == "active":
                return "✅"
            if s == "pending":
                return "⏳"
            if s == "banned":
                return "⛔"
            return "⚪"
        for u in users:
            label_base = u.get("username") or u.get("first_name") or u.get("user_id")
            label = f"{_status_emoji(u)} {label_base} ({u.get('user_id')})"
            rows.append([
                InlineKeyboardButton(label, callback_data=f"pick_user:{u.get('user_id')}")
            ])
        # Navigation row
        nav: List[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_list_users:{page-1}"))
        if (page + 1) * PAGE_SIZE < total:
            nav.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"admin_list_users:{page+1}"))
        if nav:
            rows.append(nav)
        # Search button
        rows.append([InlineKeyboardButton("🔍 Пошук за ID або @username", callback_data="admin_search_user")])
        # Cancel
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        text = (
            "Оберіть користувача зі списку або використайте пошук.\n"
            f"Сторінка {page+1}, усього користувачів: {total}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
    except Exception as e:
        try:
            await query.edit_message_text(f"Помилка завантаження списку користувачів: {e}")
        except Exception:
            pass


async def _show_users_overview_page(query, page: int):
    """Render a page with users for overview (with details buttons)."""
    try:
        criteria = {"role": {"$ne": "admin"}}
        total = um.db.users.count_documents(criteria)
        skip = max(0, page) * PAGE_SIZE
        cursor = (
            um.db.users.find(criteria, {"user_id": 1, "username": 1, "first_name": 1, "status": 1, "subscription_expires": 1, "date_added": 1})
            .sort("date_added", -1)
            .skip(skip)
            .limit(PAGE_SIZE)
        )
        users = list(cursor)
        rows: List[List[InlineKeyboardButton]] = []
        def _status_emoji(u: Dict[str, Any]) -> str:
            s = u.get("status")
            if s == "active":
                return "✅"
            if s == "pending":
                return "⏳"
            if s == "banned":
                return "⛔"
            return "⚪"
        for u in users:
            label_base = u.get("username") or u.get("first_name") or u.get("user_id")
            label = f"{_status_emoji(u)} {label_base} ({u.get('user_id')})"
            rows.append([
                InlineKeyboardButton("ℹ️ Деталі", callback_data=f"user_info:{u.get('user_id')}"),
                InlineKeyboardButton(label, callback_data=f"noop:{u.get('user_id')}")
            ])
        nav: List[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_users_page:{page-1}"))
        if (page + 1) * PAGE_SIZE < total:
            nav.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"admin_users_page:{page+1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        text = (
            "Список користувачів (перегляд деталей/посилань).\n"
            f"Сторінка {page+1}, усього користувачів: {total}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
    except Exception as e:
        try:
            await query.edit_message_text(f"Помилка завантаження: {e}")
        except Exception:
            pass


async def _show_delete_users_page(query, page: int):
    """Render a page with users for deletion selection."""
    try:
        criteria = {"role": {"$ne": "admin"}}
        total = um.db.users.count_documents(criteria)
        skip = max(0, page) * PAGE_SIZE
        cursor = (
            um.db.users.find(criteria, {"user_id": 1, "username": 1, "first_name": 1, "status": 1, "subscription_expires": 1, "date_added": 1})
            .sort("date_added", -1)
            .skip(skip)
            .limit(PAGE_SIZE)
        )
        users = list(cursor)
        rows: List[List[InlineKeyboardButton]] = []
        
        def _status_emoji(u: Dict[str, Any]) -> str:
            s = u.get("status")
            if s == "active":
                return "✅"
            if s == "pending":
                return "⏳"
            if s == "banned":
                return "⛔"
            return "⚪"
        
        for u in users:
            label_base = u.get("username") or u.get("first_name") or u.get("user_id")
            label = f"{_status_emoji(u)} {label_base} ({u.get('user_id')})"
            rows.append([
                InlineKeyboardButton(f"🗑 {label}", callback_data=f"del_user:{u.get('user_id')}")
            ])
        
        # Navigation row
        nav: List[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_delete_users_page:{page-1}"))
        if (page + 1) * PAGE_SIZE < total:
            nav.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"admin_delete_users_page:{page+1}"))
        if nav:
            rows.append(nav)
        
        # Search button
        rows.append([InlineKeyboardButton("🔍 Пошук за ID або @username", callback_data="admin_search_user_delete")])
        # Cancel
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        
        text = (
            "🗑 Видалення користувача\n\n"
            "Оберіть користувача зі списку або використайте пошук.\n"
            f"Сторінка {page+1}, усього користувачів: {total}\n\n"
            "⚠️ УВАГА: Видалення незворотне і видалить:\n"
            "• Дані користувача\n"
            "• Фільтри та посилання\n"
            "• Історію сповіщень"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
    except Exception as e:
        try:
            await query.edit_message_text(f"Помилка завантаження списку користувачів: {e}")
        except Exception:
            pass


async def admin_list_users_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination for users list in admin add-links flow."""
    query = update.callback_query
    await query.answer()
    data = query.data
    try:
        _, page_str = data.split(":", 1)
        page = int(page_str)
    except Exception:
        page = 0
    await _show_users_page(query, page)
    return CHOOSE_USER


async def admin_delete_users_page_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination for users list in admin delete flow."""
    query = update.callback_query
    await query.answer()
    data = query.data
    try:
        _, page_str = data.split(":", 1)
        page = int(page_str)
    except Exception:
        page = 0
    await _show_delete_users_page(query, page)
    return CONFIRM_DELETE


async def admin_search_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable search mode when admin clicks search button."""
    query = update.callback_query
    await query.answer()
    
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    
    # Enable search mode
    context.user_data["awaiting_user_search"] = True
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
    await query.edit_message_text(
        "🔍 Пошук користувача\n\n"
        "Надішліть ID користувача або @username для пошуку.\n\n"
        "Приклади:\n"
        "• 123456789\n"
        "• @username\n"
        "• username (без @)",
        reply_markup=kb
    )
    return CHOOSE_USER


async def admin_search_user_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable search mode when admin clicks search button in delete flow."""
    query = update.callback_query
    await query.answer()
    
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    
    # Enable search mode for deletion
    context.user_data["awaiting_user_delete_search"] = True
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
    await query.edit_message_text(
        "🔍 Пошук користувача для видалення\n\n"
        "Надішліть ID користувача або @username для пошуку.\n\n"
        "Приклади:\n"
        "• 123456789\n"
        "• @username\n"
        "• username (без @)\n\n"
        "⚠️ Користувача буде видалено повністю з бази даних!",
        reply_markup=kb
    )
    return CONFIRM_DELETE


async def search_user_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input when admin searches for a user by ID or username."""
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        return ConversationHandler.END
    
    # Check if we're expecting user search
    if not context.user_data.get("awaiting_user_search"):
        return ConversationHandler.END
    
    search_text = (update.message.text or "").strip().lstrip("@")
    
    # Try to find user by user_id or username
    user_doc = None
    if search_text.isdigit():
        # Search by user_id
        user_doc = um.db.users.find_one({"user_id": search_text})
    else:
        # Search by username (case-insensitive)
        user_doc = um.db.users.find_one({"username": {"$regex": f"^{search_text}$", "$options": "i"}})
    
    if not user_doc:
        await update.message.reply_text(
            f"❌ Користувача '{search_text}' не знайдено.\n\n"
            "Спробуйте ще раз або натисніть Скасувати.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
        )
        return CHOOSE_USER
    
    # User found, proceed to mode selection
    target_id = user_doc["user_id"]
    context.user_data["target_user_id"] = target_id
    context.user_data.pop("awaiting_user_search", None)
    
    label = user_doc.get("username") or user_doc.get("first_name") or target_id
    status = user_doc.get("status", "pending")
    status_text = "✅ активний" if status == "active" else "⏳ очікує" if status == "pending" else "❌ неактивний"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Тест (14 днів)", callback_data="mode_trial"), InlineKeyboardButton("💳 Підписка (30 днів)", callback_data="mode_subscription")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")],
    ])
    await update.message.reply_text(
        f"✅ Знайдено: {label} ({target_id})\nСтатус: {status_text}\n\nОберіть режим призначення посилань:",
        reply_markup=kb,
    )
    return CHOOSE_MODE


async def search_user_delete_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input when admin searches for a user to delete by ID or username."""
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        return ConversationHandler.END
    
    # Check if we're expecting user delete search
    if not context.user_data.get("awaiting_user_delete_search"):
        return ConversationHandler.END
    
    search_text = (update.message.text or "").strip().lstrip("@")
    
    # Try to find user by user_id or username
    user_doc = None
    if search_text.isdigit():
        # Search by user_id
        user_doc = um.db.users.find_one({"user_id": search_text})
    else:
        # Search by username (case-insensitive)
        user_doc = um.db.users.find_one({"username": {"$regex": f"^{search_text}$", "$options": "i"}})
    
    if not user_doc:
        await update.message.reply_text(
            f"❌ Користувача '{search_text}' не знайдено.\n\n"
            "Спробуйте ще раз або натисніть Скасувати.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
        )
        return CONFIRM_DELETE
    
    # Check if trying to delete admin
    if user_doc.get("role") == "admin":
        await update.message.reply_text(
            "⛔ Неможливо видалити адміністратора!\n\n"
            "Спробуйте іншого користувача або натисніть Скасувати.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
        )
        return CONFIRM_DELETE
    
    # User found, show confirmation
    target_id = user_doc["user_id"]
    context.user_data.pop("awaiting_user_delete_search", None)
    
    label = user_doc.get("username") or user_doc.get("first_name") or target_id
    status = user_doc.get("status", "pending")
    status_text = "✅ активний" if status == "active" else "⏳ очікує" if status == "pending" else "❌ неактивний"
    
    # Get additional info
    filters = um.get_user_filters(target_id)
    links_count = len(filters.get("search_urls", [])) if filters else 0
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити видалення", callback_data=f"del_user:{target_id}")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")],
    ])
    
    await update.message.reply_text(
        f"🗑 Видалення користувача\n\n"
        f"👤 Користувач: {label}\n"
        f"🆔 ID: {target_id}\n"
        f"📊 Статус: {status_text}\n"
        f"🔗 Посилань: {links_count}\n\n"
        f"⚠️ УВАГА: Видалення незворотне!\n"
        f"Буде видалено:\n"
        f"• Дані користувача\n"
        f"• Фільтри та {links_count} посилань\n"
        f"• Історію сповіщень\n\n"
        f"Підтвердити видалення?",
        reply_markup=kb,
    )
    return CONFIRM_DELETE


async def choose_mode_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data
    if mode not in ("mode_trial", "mode_subscription"):
        await query.edit_message_text("Невідомий режим.")
        return ConversationHandler.END
    context.user_data["assign_mode"] = "trial" if mode == "mode_trial" else "subscription"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
    await query.edit_message_text(
        "Надішліть одним повідомленням посилання (повні URL), можна кілька через пробіл або кому.",
        reply_markup=kb,
    )
    return ENTER_LINKS


async def enter_links_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    # Ignore non-admins or when no pending target
    if not is_admin(uid):
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    target_id = context.user_data.get("target_user_id")
    if not target_id:
        return ConversationHandler.END
    import re as _re
    links = _re.findall(r"https?://\S+", text)
    mode = context.user_data.get("assign_mode")
    um.set_user_links(target_id, links, [], access_mode=mode)
    
    # Get user's language for localized notification
    target_lang = um.get_user_language(target_id)
    
    # Start subscription period based on mode selected
    if mode == "trial":
        # Trial mode: 14 days, already set in set_user_links
        await update.message.reply_text(f"✅ Посилання оновлено для {target_id}.\n🧪 Тестовий період на 14 днів активовано.")
        await _send_setup_complete_notification(context, target_id, target_lang, skip_welcome=True)
    elif mode == "subscription":
        # Subscription mode: start 30-day paid subscription
        um.mark_paid(target_id)
        user_doc = um.db.users.find_one({"user_id": target_id}) or {}
        sub_until = user_doc.get("subscription_expires", "—")
        await update.message.reply_text(f"✅ Посилання оновлено для {target_id}.\n💳 Підписка на 30 днів активована до: {sub_until}")
        await _send_setup_complete_notification(context, target_id, target_lang, skip_welcome=True)
    else:
        await update.message.reply_text(f"Посилання оновлено для {target_id}.")
    
    # Trigger immediate parsing for this user
    # Schedule immediate asynchronous parsing for the target user
    if context.application:
        context.application.create_task(async_run_for_user(target_id, ignore_window=True))
    # Clear target to end flow
    context.user_data.pop("target_user_id", None)
    context.user_data.pop("assign_mode", None)
    return ConversationHandler.END


async def broadcast_enter_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the message text input for admin broadcast flow."""
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        return ConversationHandler.END
    message_text = (update.message.text or "").strip()
    if not message_text:
        await update.message.reply_text("Текст порожній. Спробуйте ще раз або натисніть Скасувати.")
        return BROADCAST_ENTER
    
    # Check if we're broadcasting to a specific target group
    broadcast_target = context.user_data.get("broadcast_target", "all")
    
    if broadcast_target == "not_activated":
        users = um.get_users_started_but_not_activated()
        target_description = "користувачам без активації"
    else:
        users = um.get_all_users_for_broadcast()
        target_description = "всім користувачам"
    
    if not users:
        await update.message.reply_text(f"Немає користувачів для розсилки ({target_description}).")
        context.user_data.pop("broadcast_target", None)
        return ConversationHandler.END
    
    await update.message.reply_text(f"Починаю розсилку {target_description}: {len(users)} користувачів...")
    success_count = 0
    fail_count = 0
    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        try:
            await context.bot.send_message(chat_id=user_id, text=message_text)
            success_count += 1
        except Exception as e:
            fail_count += 1
            print(f"Failed to send to {user_id}: {e}")
    
    await update.message.reply_text(
        f"✅ Розсилка завершена!\n"
        f"Цільова група: {target_description}\n"
        f"Успішно: {success_count}\n"
        f"Помилок: {fail_count}"
    )
    
    # Clear broadcast target
    context.user_data.pop("broadcast_target", None)
    return ConversationHandler.END


async def admin_menu_back_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler to go back to admin menu."""
    query = update.callback_query
    await query.answer()
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    await query.edit_message_text("Адмін-меню:", reply_markup=_admin_menu_keyboard())
    return ADMIN_MENU


async def admin_broadcast_not_activated_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler to broadcast message to users who started but didn't activate."""
    query = update.callback_query
    await query.answer()
    uid = str(update.effective_user.id)
    if not is_admin(uid):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    
    # Mark that we want to broadcast to non-activated users
    context.user_data["broadcast_target"] = "not_activated"
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")]])
    await query.edit_message_text(
        "📣 Розсилка користувачам без активації\n\n"
        "Надішліть текст повідомлення для розсилки користувачам, які стартували бота, але не активували підписку.",
        reply_markup=kb,
    )
    return BROADCAST_ENTER


async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text("Скасовано.")
    else:
        await update.message.reply_text("Скасовано.")
    # Clear any broadcast target
    context.user_data.pop("broadcast_target", None)
    return ConversationHandler.END


def _admin_menu_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("admin", admin_menu),
            # Allow starting the admin conversation from inline buttons shown on /start
            CallbackQueryHandler(admin_menu_cb, pattern=r"^admin_(add_links|broadcast|delete|cancel|paid|cancel_sub|users|not_activated)$"),
        ],
        states={
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_cb, pattern=r"^admin_(add_links|broadcast|delete|cancel|paid|users|not_activated)$"),
                CallbackQueryHandler(admin_users_page_cb, pattern=r"^admin_users_page:\d+$"),
                CallbackQueryHandler(user_info_cb, pattern=r"^user_info:.*$"),
                CallbackQueryHandler(noop_cb, pattern=r"^noop:.*$"),
                CallbackQueryHandler(admin_menu_back_cb, pattern=r"^admin_menu_back$"),
                CallbackQueryHandler(admin_broadcast_not_activated_cb, pattern=r"^admin_broadcast_not_activated$"),
                CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$"),
            ],
            CHOOSE_USER: [
                CallbackQueryHandler(pick_user_cb, pattern=r"^pick_user:.*$"),
                CallbackQueryHandler(admin_list_users_cb, pattern=r"^admin_list_users:\\d+$"),
                CallbackQueryHandler(admin_search_user_cb, pattern=r"^admin_search_user$"),
                CallbackQueryHandler(cancel_subscription_cb, pattern=r"^cancel_sub:.*$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_user_msg),
                CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$")
            ],
            CHOOSE_MODE: [CallbackQueryHandler(choose_mode_cb, pattern=r"^mode_(trial|subscription)$")],
            CONFIRM_DELETE: [
                CallbackQueryHandler(confirm_delete_cb, pattern=r"^del_user:.*$|^admin_cancel$"),
                CallbackQueryHandler(admin_delete_users_page_cb, pattern=r"^admin_delete_users_page:\d+$"),
                CallbackQueryHandler(admin_search_user_delete_cb, pattern=r"^admin_search_user_delete$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_user_delete_msg),
            ],
            ENTER_LINKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_links_msg),
                CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$")
            ],
            BROADCAST_ENTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_enter_msg),
                CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$")
            ],
            CHOOSE_USER_PAID: [
                CallbackQueryHandler(mark_paid_cb, pattern=r"^mark_paid:.*$"),
                CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_cb)],
        allow_reentry=True,
    )


# Global handlers to catch button clicks even when menu shown via /start
def register_global_admin_handlers(app: Application):
    # These are callback-only handlers. They don't consume text messages, so they won't
    # interfere with ConversationHandler text states. They make admin menu buttons work
    # even when shown outside the /admin conversation (e.g., from /start).
    app.add_handler(CallbackQueryHandler(admin_menu_cb, pattern=r"^admin_(add_links|broadcast|delete|cancel|paid|cancel_sub|users|not_activated)$"))
    app.add_handler(CallbackQueryHandler(pick_user_cb, pattern=r"^pick_user:.*$"))
    app.add_handler(CallbackQueryHandler(admin_list_users_cb, pattern=r"^admin_list_users:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_search_user_cb, pattern=r"^admin_search_user$"))
    app.add_handler(CallbackQueryHandler(admin_users_page_cb, pattern=r"^admin_users_page:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_users_page_cb, pattern=r"^admin_delete_users_page:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_search_user_delete_cb, pattern=r"^admin_search_user_delete$"))
    app.add_handler(CallbackQueryHandler(user_info_cb, pattern=r"^user_info:.*$"))
    app.add_handler(CallbackQueryHandler(noop_cb, pattern=r"^noop:.*$"))
    app.add_handler(CallbackQueryHandler(admin_menu_back_cb, pattern=r"^admin_menu_back$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_not_activated_cb, pattern=r"^admin_broadcast_not_activated$"))
    app.add_handler(CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$"))
    app.add_handler(CallbackQueryHandler(choose_mode_cb, pattern=r"^mode_(trial|subscription)$"))
    app.add_handler(CallbackQueryHandler(confirm_delete_cb, pattern=r"^del_user:.*$"))
    app.add_handler(CallbackQueryHandler(mark_paid_cb, pattern=r"^mark_paid:.*$"))
    app.add_handler(CallbackQueryHandler(cancel_subscription_cb, pattern=r"^cancel_sub:.*$"))
    # Note: do NOT register any MessageHandler here.


async def noop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """No-op callback for informational buttons that do nothing."""
    query = update.callback_query
    await query.answer()
    # Don't change anything, just acknowledge the click
    return ADMIN_MENU


async def admin_users_page_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    try:
        _, page_str = data.split(":", 1)
        page = int(page_str)
    except Exception:
        page = 0
    await _show_users_overview_page(query, page)
    return ADMIN_MENU


def _fmt_dt(iso: Any) -> str:
    try:
        if not iso:
            return "—"
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(iso)).strftime("%d.%m.%Y")
    except Exception:
        return str(iso)


async def user_info_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("user_info:"):
        return ADMIN_MENU
    uid = data.split(":", 1)[1]
    try:
        user = um.db.users.find_one({"user_id": uid}) or {}
        f = um.get_user_filters(uid) or {}
        links: List[str] = f.get("search_urls", []) or []
        cities: List[str] = f.get("preferred_locations", []) or []
        links_preview = links[:15]
        more = len(links) - len(links_preview)
        status = user.get("status", "—")
        text_lines = [
            f"👤 ID: {uid}",
            f"Username: @{user.get('username') or '—'}",
            f"Статус: {status}",
            f"Активна до: {_fmt_dt(user.get('subscription_expires'))}",
            f"Дата активації: {_fmt_dt(user.get('date_activated'))}",
            f"Міст(а): {', '.join(cities) if cities else '—'}",
            f"Посилання ({len(links)}):" if links else "Посилання: —",
        ]
        for url in links_preview:
            text_lines.append(f"• {url}")
        if more > 0:
            text_lines.append(f"… та ще {more} посилань")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_users")]
        ])
        await query.edit_message_text("\n".join(text_lines), reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        try:
            await query.edit_message_text(f"Помилка: {e}")
        except Exception:
            pass
    return ADMIN_MENU


async def mark_paid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin callback to confirm payment and activate subscription for a user."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("mark_paid:"):
        await query.edit_message_text("Помилка вибору користувача.")
        return ConversationHandler.END
    uid = data.split(":", 1)[1]
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    um.mark_paid(uid)
    user_doc = um.db.users.find_one({"user_id": uid}) or {}
    sub_until = user_doc.get("subscription_expires", "—")
    await query.edit_message_text(f"💳 Оплату підтверджено. Підписку для {uid} активовано до: {sub_until}")
    # Notify user
    try:
        await context.bot.send_message(chat_id=uid, text=f"💳 Оплату підтверджено. Підписка активна до: {sub_until}")
    except Exception:
        pass
    return ConversationHandler.END


async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    if not context.args:
        await update.message.reply_text("Використання: /delete_user <user_id>")
        return
    target_id = context.args[0]
    if um.delete_user(target_id):
        await update.message.reply_text(f"Користувача {target_id} видалено.")
    else:
        await update.message.reply_text("Не вдалося видалити (можливо, користувача не знайдено або це адмін).")


async def confirm_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "admin_cancel":
        await query.edit_message_text("Скасовано.")
        return ConversationHandler.END
    if not data.startswith("del_user:"):
        await query.edit_message_text("Помилка вибору користувача.")
        return ConversationHandler.END
    target_id = data.split(":", 1)[1]
    
    # Get user info before deletion for confirmation message
    user_doc = um.db.users.find_one({"user_id": target_id})
    if not user_doc:
        await query.edit_message_text(f"❌ Користувача {target_id} не знайдено в базі даних.")
        return ConversationHandler.END
    
    label = user_doc.get("username") or user_doc.get("first_name") or target_id
    
    # Get stats before deletion
    filters = um.get_user_filters(target_id)
    links_count = len(filters.get("search_urls", [])) if filters else 0
    notifications_count = um.db.notification_stats.count_documents({"recipient_id": target_id})
    
    # Perform deletion
    if um.delete_user(target_id):
        await query.edit_message_text(
            f"✅ Користувача успішно видалено!\n\n"
            f"👤 {label} (ID: {target_id})\n\n"
            f"Видалено:\n"
            f"• Дані користувача\n"
            f"• {links_count} посилань\n"
            f"• {notifications_count} записів сповіщень\n\n"
            f"Користувач може зареєструватися знову через /start"
        )
    else:
        await query.edit_message_text(
            f"❌ Не вдалося видалити користувача {target_id}\n\n"
            f"Можливо, це адміністратор або користувача не існує."
        )
    return ConversationHandler.END


# ---- User subscribe flow ----
async def cancel_subscription_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin callback to cancel a user's active subscription immediately."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("cancel_sub:"):
        await query.edit_message_text("Помилка вибору користувача.")
        return ConversationHandler.END
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    uid = data.split(":", 1)[1]
    now_iso = datetime.utcnow().isoformat()
    # Set subscription to expired and mark user inactive. Do not remove links.
    um.db.users.update_one(
        {"user_id": uid},
        {"$set": {"subscription_expires": now_iso, "status": "inactive", "awaiting_payment": False},
         "$unset": {"requested_subscription": ""}}
    )
    await query.edit_message_text(f"❎ Підписку користувача {uid} скасовано.")
    # Notify the user
    try:
        contact = SUPPORT_CONTACT or "@admin"
        await context.bot.send_message(
            chat_id=uid,
            text=(
                "❎ Вашу підписку скасовано адміністратором.\n"
                f"Якщо це помилка — зверніться до підтримки: {contact}"
            )
        )
    except Exception:
        pass
    return ConversationHandler.END


async def quick_assign_mode_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mode selection for quick assign (trial or subscription)."""
    query = update.callback_query
    await query.answer()
    
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return
    
    data = query.data
    
    if data == "quick_assign_cancel":
        await query.edit_message_text("❌ Призначення скасовано.")
        context.user_data.pop("quick_assign_target_id", None)
        context.user_data.pop("quick_assign_links", None)
        context.user_data.pop("quick_assign_label", None)
        return
    
    target_id = context.user_data.get("quick_assign_target_id")
    links = context.user_data.get("quick_assign_links")
    label = context.user_data.get("quick_assign_label", target_id)
    
    if not target_id or not links:
        await query.edit_message_text("❌ Помилка: дані не знайдено. Спробуйте ще раз.")
        return
    
    # Determine mode
    if data == "quick_assign_trial":
        mode = "trial"
        mode_text = "🧪 Тест (14 днів)"
    elif data == "quick_assign_subscription":
        mode = "subscription"
        mode_text = "💳 Підписка (30 днів)"
    else:
        await query.edit_message_text("❌ Невідомий режим.")
        return
    
    # Assign links
    um.set_user_links(target_id, links, [], access_mode=mode)
    
    # Get user's language for localized notification
    target_lang = um.get_user_language(target_id)
    
    # Activate subscription based on mode
    from datetime import datetime as _dt
    if mode == "trial":
        um.mark_trial(target_id)
        user_doc = um.db.users.find_one({"user_id": target_id}) or {}
        sub_until = user_doc.get("subscription_expires", "—")
        try:
            sub_until_formatted = _dt.fromisoformat(sub_until).strftime("%d.%m.%Y")
        except Exception:
            sub_until_formatted = sub_until
        
        await query.edit_message_text(
            f"✅ Посилання призначено!\n\n"
            f"👤 Користувач: {label} (ID: {target_id})\n"
            f"📎 Посилань: {len(links)}\n"
            f"🧪 Тестовий період активовано до: {sub_until_formatted}\n\n"
            f"Користувач отримає повідомлення."
        )
        
        # Notify user in their language
        await _send_setup_complete_notification(context, target_id, target_lang, skip_welcome=True)
    
    elif mode == "subscription":
        um.mark_paid(target_id)
        user_doc = um.db.users.find_one({"user_id": target_id}) or {}
        sub_until = user_doc.get("subscription_expires", "—")
        try:
            sub_until_formatted = _dt.fromisoformat(sub_until).strftime("%d.%m.%Y")
        except Exception:
            sub_until_formatted = sub_until
        
        await query.edit_message_text(
            f"✅ Посилання призначено!\n\n"
            f"👤 Користувач: {label} (ID: {target_id})\n"
            f"📎 Посилань: {len(links)}\n"
            f"💳 Підписка активована до: {sub_until_formatted}\n\n"
            f"Користувач отримає повідомлення."
        )
        
        # Notify user in their language
        await _send_setup_complete_notification(context, target_id, target_lang, skip_welcome=True)
    
    # Trigger immediate parsing
    if context.application:
        context.application.create_task(async_run_for_user(target_id, ignore_window=True))
    
    # Clear context
    context.user_data.pop("quick_assign_target_id", None)
    context.user_data.pop("quick_assign_links", None)
    context.user_data.pop("quick_assign_label", None)


async def user_add_cities_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the user setup request conversation when user clicks 'Add more cities'."""
    query = update.callback_query
    await query.answer()
    u = query.from_user
    uid = str(u.id)
    
    try:
        # Get user's language
        user_lang = um.get_user_language(uid)
        
        # Show warning about overwriting parameters
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text("btn_back_menu", user_lang), callback_data="user_setup_cancel")]])
        await context.bot.send_message(
            chat_id=uid,
            text=get_text("setup_add_cities_warning", user_lang),
            reply_markup=cancel_kb
        )
        
        # Start setup conversation - ask for city
        await context.bot.send_message(
            chat_id=uid,
            text=get_text("setup_ask_city", user_lang),
            reply_markup=cancel_kb
        )
        
        # Store language in context for conversation
        context.user_data["setup_user_lang"] = user_lang
        context.user_data["setup_user_id"] = uid
        context.user_data["setup_from_menu"] = True  # Mark that this request is from menu
        
        return USER_SETUP_ASK_CITY
        
    except Exception as e:
        print(f"Error starting add cities for {uid}: {e}")
        import traceback
        traceback.print_exc()
        return ConversationHandler.END


async def user_subscribe_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the user setup request conversation when user clicks 'Try 14 days FREE'."""
    query = update.callback_query
    await query.answer()
    u = query.from_user
    uid = str(u.id)
    
    try:
        # Ensure user document exists (edge case: if /start didn't create it)
        if not um.db.users.find_one({"user_id": uid}):
            um.upsert_user(uid, u.username or "", u.first_name or "", u.last_name or "")
        
        # Get user's language
        user_lang = um.get_user_language(uid)
        
        # Check if user already has active subscription or trial
        user_doc = um.db.users.find_one({"user_id": uid}) or {}
        from datetime import datetime as _dt
        now = _dt.utcnow()
        has_active = False
        
        # Check if subscription is still active
        sub_expires = user_doc.get("subscription_expires")
        if sub_expires:
            try:
                has_active = _dt.fromisoformat(sub_expires) > now
            except Exception:
                pass
        
        # If user already has active subscription, show info message
        if has_active:
            sub_until = user_doc.get("subscription_expires", "—")
            try:
                sub_until_formatted = _dt.fromisoformat(sub_until).strftime("%d.%m.%Y")
            except Exception:
                sub_until_formatted = sub_until
            
            message_text = get_text("trial_already_active", user_lang, date=sub_until_formatted)
            await context.bot.send_message(
                chat_id=uid,
                text=message_text,
                reply_markup=_back_to_menu_keyboard(user_lang),
            )
            return ConversationHandler.END
        
        # Activate trial immediately
        um.mark_trial(uid)
        
        # Start setup conversation - ask for city
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text("btn_back_menu", user_lang), callback_data="user_setup_cancel")]])
        await context.bot.send_message(
            chat_id=uid,
            text=get_text("setup_ask_city", user_lang),
            reply_markup=cancel_kb
        )
        
        # Store language in context for conversation
        context.user_data["setup_user_lang"] = user_lang
        context.user_data["setup_user_id"] = uid
        
        return USER_SETUP_ASK_CITY
        
    except Exception as e:
        print(f"Error starting setup for {uid}: {e}")
        import traceback
        traceback.print_exc()
        return ConversationHandler.END


async def admin_inline_approve_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 1)[1]
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return
    # Ensure user exists before approval (fallback)
    user_doc = um.db.users.find_one({"user_id": uid})
    if not user_doc:
        # Create a minimal pending doc then approve
        um.upsert_user(uid, "", "", "")
    
    # Activate 14-day free trial immediately
    um.mark_trial(uid)
    
    # Get subscription expiration date for notification
    user_doc = um.db.users.find_one({"user_id": uid}) or {}
    sub_until = user_doc.get("subscription_expires", "—")
    from datetime import datetime as _dt
    try:
        sub_until_formatted = _dt.fromisoformat(sub_until).strftime("%d.%m.%Y")
    except Exception:
        sub_until_formatted = sub_until
    
    await query.edit_message_text(f"✅ Користувача {uid} схвалено. 14-денний триал активовано до: {sub_until_formatted}")
    
    # Notify user about trial activation
    try:
        await context.bot.send_message(chat_id=uid, text=(
            f"🎉 Вітаємо! Тестовий період на 14 днів активовано!\n\n"
            f"📅 Підписка активна до: {sub_until_formatted}\n\n"
            "Тепер додай свої посилання пошуку, і бот почне шукати для тебе квартири!"
        ))
    except Exception:
        pass
    # Start immediate parsing for this user (if they already have links)
    if context.application:
        context.application.create_task(async_run_for_user(uid, ignore_window=True))


async def admin_inline_decline_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 1)[1]
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return
    await query.edit_message_text(f"Заявку користувача {uid} відхилено.")
    try:
        um.db.users.update_one({"user_id": uid}, {"$unset": {"requested_subscription": ""}})
        await context.bot.send_message(chat_id=uid, text="На жаль, вашу заявку відхилено. Зв'яжіться з адміністратором для уточнення.")
    except Exception:
        pass


async def admin_quick_add_links_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for 'Add links' button from setup request notification.
    Initiates a flow to add links to the user who submitted the setup request.
    """
    query = update.callback_query
    await query.answer()
    
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    
    # Extract user_id from callback data
    if not query.data.startswith("admin_quick_add_links:"):
        await query.edit_message_text("❌ Помилка: невірний формат даних.")
        return ConversationHandler.END
    
    target_id = query.data.split(":", 1)[1]
    
    # Verify user exists
    user_doc = um.db.users.find_one({"user_id": target_id})
    if not user_doc:
        await query.edit_message_text(f"❌ Користувача {target_id} не знайдено.")
        return ConversationHandler.END
    
    label = user_doc.get("username") or user_doc.get("first_name") or target_id
    
    # Store target user in context
    context.user_data["quick_add_target_id"] = target_id
    context.user_data["quick_add_label"] = label
    
    # Ask admin to choose mode: trial or subscription
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧪 Тест (14 днів)", callback_data="quick_add_mode_trial"),
            InlineKeyboardButton("💳 Підписка (30 днів)", callback_data="quick_add_mode_subscription")
        ],
        [InlineKeyboardButton("❌ Скасувати", callback_data="quick_add_cancel")]
    ])
    
    await query.edit_message_text(
        f"📋 Призначення посилань для:\n"
        f"👤 {label} (ID: {target_id})\n\n"
        f"Оберіть режим доступу:",
        reply_markup=kb
    )
    
    return QUICK_ADD_CHOOSE_MODE


async def admin_quick_add_mode_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for mode selection in quick add links flow."""
    query = update.callback_query
    await query.answer()
    
    if not is_admin(str(query.from_user.id)):
        await query.edit_message_text("Лише адміністратор може виконувати цю дію.")
        return ConversationHandler.END
    
    data = query.data
    
    if data == "quick_add_cancel":
        await query.edit_message_text("❌ Призначення скасовано.")
        context.user_data.pop("quick_add_target_id", None)
        context.user_data.pop("quick_add_label", None)
        context.user_data.pop("quick_add_mode", None)
        return ConversationHandler.END
    
    # Determine mode
    if data == "quick_add_mode_trial":
        mode = "trial"
        mode_text = "🧪 Тест (14 днів)"
    elif data == "quick_add_mode_subscription":
        mode = "subscription"
        mode_text = "💳 Підписка (30 днів)"
    else:
        await query.edit_message_text("❌ Невідомий режим.")
        return ConversationHandler.END
    
    # Store mode in context
    context.user_data["quick_add_mode"] = mode
    
    target_id = context.user_data.get("quick_add_target_id")
    label = context.user_data.get("quick_add_label", target_id)
    
    # Ask admin to enter links
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="quick_add_cancel")]])
    
    await query.edit_message_text(
        f"📋 Режим: {mode_text}\n"
        f"👤 Користувач: {label}\n\n"
        f"📎 Надішліть посилання одним повідомленням.\n"
        f"Можна вставити кілька посилань (кожне на новому рядку або через пробіл).\n\n"
        f"Приклад:\n"
        f"https://www.kleinanzeigen.de/...\n"
        f"https://www.immowelt.de/...",
        reply_markup=kb
    )
    
    return QUICK_ADD_ENTER_LINKS


async def admin_quick_add_enter_links_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for links input in quick add links flow."""
    uid = str(update.effective_user.id)
    
    if not is_admin(uid):
        return ConversationHandler.END
    
    # Extract links from message
    text = (update.message.text or "").strip()
    
    import re as _re
    links = _re.findall(r"https?://\S+", text)
    
    if not links:
        await update.message.reply_text(
            "❌ Не знайдено жодного посилання.\n\n"
            "Переконайтеся, що ви надіслали URL (https://...).\n"
            "Спробуйте ще раз або натисніть Скасувати.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Скасувати", callback_data="quick_add_cancel")]])
        )
        return QUICK_ADD_ENTER_LINKS
    
    target_id = context.user_data.get("quick_add_target_id")
    label = context.user_data.get("quick_add_label", target_id)
    mode = context.user_data.get("quick_add_mode")
    
    if not target_id or not mode:
        await update.message.reply_text("❌ Помилка: дані не знайдено. Спробуйте ще раз.")
        return ConversationHandler.END
    
    # Assign links to user
    um.set_user_links(target_id, links, [], access_mode=mode)
    
    # Get user's language for localized notification
    target_lang = um.get_user_language(target_id)
    
    # Activate subscription based on mode
    from datetime import datetime as _dt
    if mode == "trial":
        um.mark_trial(target_id)
        user_doc = um.db.users.find_one({"user_id": target_id}) or {}
        sub_until = user_doc.get("subscription_expires", "—")
        try:
            sub_until_formatted = _dt.fromisoformat(sub_until).strftime("%d.%m.%Y")
        except Exception:
            sub_until_formatted = sub_until
        
        links_preview = "\n".join([f"• {url}" for url in links[:5]])
        if len(links) > 5:
            links_preview += f"\n... та ще {len(links) - 5} посилань"
        
        await update.message.reply_text(
            f"✅ Посилання призначено!\n\n"
            f"👤 Користувач: {label} (ID: {target_id})\n"
            f"📎 Посилань: {len(links)}\n{links_preview}\n\n"
            f"🧪 Тестовий період активовано до: {sub_until_formatted}\n\n"
            f"Користувач отримає повідомлення."
        )
        
        # Notify user in their language
        await _send_setup_complete_notification(context, target_id, target_lang, skip_welcome=True)
    
    elif mode == "subscription":
        um.mark_paid(target_id)
        user_doc = um.db.users.find_one({"user_id": target_id}) or {}
        sub_until = user_doc.get("subscription_expires", "—")
        try:
            sub_until_formatted = _dt.fromisoformat(sub_until).strftime("%d.%m.%Y")
        except Exception:
            sub_until_formatted = sub_until
        
        links_preview = "\n".join([f"• {url}" for url in links[:5]])
        if len(links) > 5:
            links_preview += f"\n... та ще {len(links) - 5} посилань"
        
        await update.message.reply_text(
            f"✅ Посилання призначено!\n\n"
            f"👤 Користувач: {label} (ID: {target_id})\n"
            f"📎 Посилань: {len(links)}\n{links_preview}\n\n"
            f"💳 Підписка активована до: {sub_until_formatted}\n\n"
            f"Користувач отримає повідомлення."
        )
        
        # Notify user in their language
        await _send_setup_complete_notification(context, target_id, target_lang, skip_welcome=True)
    
    # Trigger immediate parsing
    if context.application:
        context.application.create_task(async_run_for_user(target_id, ignore_window=True))
    
    # Clear context
    context.user_data.pop("quick_add_target_id", None)
    context.user_data.pop("quick_add_label", None)
    context.user_data.pop("quick_add_mode", None)
    
    return ConversationHandler.END


# ---- User menu handlers ----
async def user_support_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = str(q.from_user.id)
    user_lang = um.get_user_language(uid)
    # Import support contact from config was done at top; fallback if empty
    contact = SUPPORT_CONTACT or "@admin"
    try:
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=get_text("support_text", user_lang, contact=contact),
            reply_markup=_back_to_menu_keyboard(user_lang),
        )
    except Exception:
        pass


async def user_sub_info_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = str(q.from_user.id)
    user_lang = um.get_user_language(uid)
    u = um.db.users.find_one({"user_id": uid})
    status = (u or {}).get("status")
    subscription_expires = (u or {}).get("subscription_expires")
    requested = (u or {}).get("requested_subscription")

    # Беремо інформацію і про триал, і про платну підписку
    from datetime import datetime as _dt
    now = _dt.utcnow()

    def _fmt_date(iso: str) -> str:
        try:
            dt = _dt.fromisoformat(iso)
            return dt.strftime("%d.%m.%Y")
        except Exception:
            return iso

    # Спробуємо знайти активний триал у фільтрах
    f = um.db.user_filters.find_one({"user_id": uid}) or {}
    trial_expires = f.get("trial_expires_at")
    trial_active = False
    if trial_expires:
        try:
            trial_active = now <= _dt.fromisoformat(trial_expires)
        except Exception:
            trial_active = False

    paid_active = False
    if subscription_expires:
        try:
            paid_active = now <= _dt.fromisoformat(subscription_expires)
        except Exception:
            paid_active = False

    if paid_active:
        msg = get_text("sub_info_text", user_lang, date=_fmt_date(subscription_expires))
    elif trial_active:
        msg = get_text("sub_trial_until", user_lang, date=_fmt_date(trial_expires))
    elif requested:
        msg = get_text("sub_request_pending", user_lang)
    else:
        msg = get_text("sub_not_active", user_lang)
    
    try:
        await context.bot.send_message(chat_id=q.message.chat_id, text=msg, reply_markup=_back_to_menu_keyboard(user_lang))
    except Exception:
        pass


async def user_back_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        uid = str(q.from_user.id)
        user_lang = um.get_user_language(uid)
        await _ensure_user_menu(context, uid, get_text("welcome_text", user_lang))
        if uid not in _reply_kb_set:
            label = "Меню" if user_lang in ("uk", "ru") else ("القائمة" if user_lang == "ar" else "Menu")
            rk = ReplyKeyboardMarkup([[label]], resize_keyboard=True)
            try:
                await q.message.reply_text(get_text("menu_hint", user_lang), reply_markup=rk)
                _reply_kb_set.add(uid)
            except Exception:
                pass
    except Exception:
        pass


async def language_selection_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection from user."""
    q = update.callback_query
    await q.answer()
    
    uid = str(q.from_user.id)
    data = q.data
    
    # Extract language code from callback data (lang_uk, lang_ru, lang_ar)
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        
        # Save user's language preference
        um.set_user_language(uid, lang)
        
        # Show language confirmation
        confirmation = get_text("language_selected", lang)
        await q.edit_message_text(confirmation)
        
        # Show welcome message in selected language
        await _ensure_user_menu(context, uid, get_text("welcome_text", lang))
        # Ensure reply keyboard exists
        if uid not in _reply_kb_set:
            label = "Меню" if lang in ("uk", "ru") else ("القائمة" if lang == "ar" else "Menu")
            rk = ReplyKeyboardMarkup([[label]], resize_keyboard=True)
            try:
                await context.bot.send_message(chat_id=uid, text=get_text("menu_hint", lang), reply_markup=rk)
                _reply_kb_set.add(uid)
            except Exception:
                pass


async def user_change_lang_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language change request from user menu."""
    q = update.callback_query
    await q.answer()
    
    uid = str(q.from_user.id)
    user_lang = um.get_user_language(uid)
    
    try:
        await q.edit_message_text(
            get_text("select_language", user_lang),
            reply_markup=_language_selection_keyboard()
        )
    except Exception:
        # If edit fails, send new message
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=get_text("select_language", user_lang),
            reply_markup=_language_selection_keyboard()
        )


# ---- Inline Menu Utility Commands ----
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Universal command to (re)show inline menu for any user (old/new)."""
    uid = str(update.effective_user.id)
    if is_admin(uid):
        await _ensure_admin_menu(context, uid)
        return
    # Regular user: fetch language and show welcome + dynamic menu
    user_lang = um.get_user_language(uid)
    await _ensure_user_menu(context, uid, get_text("welcome_text", user_lang))
    if uid not in _reply_kb_set:
        label = "Меню" if user_lang in ("uk", "ru") else ("القائمة" if user_lang == "ar" else "Menu")
        rk = ReplyKeyboardMarkup([[label]], resize_keyboard=True)
        try:
            await update.message.reply_text(get_text("menu_hint", user_lang), reply_markup=rk)
            _reply_kb_set.add(uid)
        except Exception:
            pass


async def push_menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: push the inline menu message to all users (existing + new)."""
    caller_id = str(update.effective_user.id)
    if not is_admin(caller_id):
        await update.message.reply_text("Лише адміністратор може виконувати цю команду.")
        return
    users = um.get_all_users_for_broadcast()
    if not users:
        await update.message.reply_text("Немає користувачів для надсилання меню.")
        return
    await update.message.reply_text(f"Розсилка меню {len(users)} користувачам...")
    sent = 0
    failed = 0
    for user in users:
        uid = user.get("user_id")
        if not uid:
            continue
        try:
            lang = um.get_user_language(uid)
            await _ensure_user_menu(context, uid, get_text("welcome_text", lang))
            sent += 1
            if uid not in _reply_kb_set:
                label = "Меню" if lang in ("uk", "ru") else ("القائمة" if lang == "ar" else "Menu")
                rk = ReplyKeyboardMarkup([[label]], resize_keyboard=True)
                try:
                    await context.bot.send_message(chat_id=uid, text=get_text("menu_hint", lang), reply_markup=rk)
                    _reply_kb_set.add(uid)
                except Exception:
                    pass
        except Exception as e:
            failed += 1
            print(f"Failed to push menu to {uid}: {e}")
    await update.message.reply_text(f"✅ Меню надіслано: {sent}\n❌ Помилок: {failed}")

# Text-based menu button handler (reply keyboard single button)
async def menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text not in ("Меню", "Menu", "القائمة"):
        return
    uid = str(update.effective_user.id)
    if is_admin(uid):
        await _ensure_admin_menu(context, uid)
        return
    user_lang = um.get_user_language(uid)
    await _ensure_user_menu(context, uid, get_text("welcome_text", user_lang))
    # Re-send reply keyboard if lost
    if uid not in _reply_kb_set:
        label = "Меню" if user_lang in ("uk", "ru") else ("القائمة" if user_lang == "ar" else "Menu")
        rk = ReplyKeyboardMarkup([[label]], resize_keyboard=True)
        try:
            await update.message.reply_text(get_text("menu_hint", user_lang), reply_markup=rk)
            _reply_kb_set.add(uid)
        except Exception:
            pass
