# -*- coding: utf-8 -*-
from typing import Dict, Any, List
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
)
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, SUPPORT_CONTACT
from .user_manager import UserManager
from .runner import async_run_for_user, async_run_cycle

um = UserManager()

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    uid = str(u.id)
    if is_admin(uid):
        # Ensure admin is recorded as active admin, no pending text
        um.upsert_user(uid, u.username or "", u.first_name or "", u.last_name or "")
        um.db.users.update_one(
            {"user_id": uid},
            {"$set": {"role": "admin", "status": "active", "date_activated": datetime.utcnow().isoformat()}},
        )
        await update.message.reply_text(
            "Ви адміністратор. Доступ активний. Нижче — адмін-меню.",
            reply_markup=_admin_menu_keyboard()
        )
        return
    # Regular user path: show user menu (support, subscription date, start), register/update user as pending
    um.upsert_user(uid, u.username or "", u.first_name or "", u.last_name or "")
    await update.message.reply_text(WELCOME_TEXT, reply_markup=_user_menu_keyboard())


def _user_menu_keyboard(uid: str | None = None):
    """Build user menu. For new/inactive users, do NOT show subscribe button.
    The subscribe button is intentionally hidden to avoid showing it to new users.
    """
    rows = [
        [InlineKeyboardButton("🛠️ Техпідтримка", callback_data="user_support")],
        [InlineKeyboardButton("📅 Дата початку підписки", callback_data="user_sub_info")],
    ]
    # If in future we decide to show additional actions for active users, we can append here
    return InlineKeyboardMarkup(rows)


def _back_to_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Головне меню", callback_data="user_back_menu")]])

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
            "/start\n/admin — відкрити адмін-меню\n/users — список користувачів та посилань\n/approve <user_id> — схвалити користувача\n"
            "/set_location <user_id> <посилання...> ; cities=Місто1,Місто2 — призначити міста/посилання\n"
            "/view_location <user_id> — переглянути міста/посилання\n/delete_user <user_id> — видалити користувача\n"
            "/set_links <url1 url2 ...> — задати посилання собі\n/test_run — тестовий запуск парсингу\n"
            "/broadcast <текст> — розсилка повідомлення всім користувачам\n"
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
    # Set default (non-admin) commands
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Почати"),
                BotCommand("help", "Як користуватися ботом"),
                BotCommand("support", "Техпідтримка"),
                BotCommand("status", "Статус підписки"),
            ],
            scope=BotCommandScopeDefault(),
        )
    except Exception:
        pass
    # Set admin-specific commands per admin chat
    for aid in _admin_ids:
        try:
            await app.bot.set_my_commands(
                [
                    BotCommand("start", "Почати (адмін)"),
                    BotCommand("admin", "Відкрити адмін-меню"),
                    BotCommand("users", "Список користувачів та посилань"),
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
        except Exception:
            pass


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


def build_app():
    from telegram.ext import JobQueue
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).job_queue(JobQueue()).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("support", support_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("menu", admin_menu))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("delete_user", delete_user))
    app.add_handler(CommandHandler("set_location", set_location))
    app.add_handler(CommandHandler("view_location", view_location))
    app.add_handler(CommandHandler("set_links", set_links))
    app.add_handler(CommandHandler("test_run", test_run))
    app.add_handler(CommandHandler("force_run", force_run_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("help", help_cmd))
    
    # User menu callbacks - MUST be registered BEFORE ConversationHandler to avoid being captured
    app.add_handler(CallbackQueryHandler(user_support_cb, pattern=r"^user_support$"))
    app.add_handler(CallbackQueryHandler(user_sub_info_cb, pattern=r"^user_sub_info$"))
    app.add_handler(CallbackQueryHandler(user_subscribe_cb, pattern=r"^user_subscribe$"))
    app.add_handler(CallbackQueryHandler(user_back_menu_cb, pattern=r"^user_back_menu$"))
    
    # Admin inline approve/decline from user subscribe request
    app.add_handler(CallbackQueryHandler(admin_inline_approve_cb, pattern=r"^admin_inline_approve:"))
    app.add_handler(CallbackQueryHandler(admin_inline_decline_cb, pattern=r"^admin_inline_decline:"))
    
    # Admin inline menu conversation - comes AFTER user callbacks
    app.add_handler(_admin_menu_conv())
    # Global admin handlers enabled so inline admin menu from /start works outside the conversation
    register_global_admin_handlers(app)
    
    return app


# ---- Admin Inline Menu Conversation ----
# Added BROADCAST_ENTER state for admin broadcast flow and CHOOSE_USER_PAID for payment confirmation
ADMIN_MENU, CHOOSE_USER, CHOOSE_MODE, ENTER_LINKS, CONFIRM_DELETE, BROADCAST_ENTER, CHOOSE_USER_PAID = range(7)

# Pagination size for admin user list
PAGE_SIZE = 10


def _admin_menu_keyboard():
    kb = [
        [InlineKeyboardButton("👥 Користувачі та посилання", callback_data="admin_users")],
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
        # list users to pick for deletion
        users = list(um.db.users.find({"role": {"$ne": "admin"}}, {"user_id": 1, "username": 1, "first_name": 1}).limit(10))
        if not users:
            await query.edit_message_text("Немає користувачів для видалення.")
            return ConversationHandler.END
        rows = []
        for u in users:
            label = u.get("username") or u.get("first_name") or u.get("user_id")
            rows.append([InlineKeyboardButton(f"Видалити {label} ({u['user_id']})", callback_data=f"del_user:{u['user_id']}")])
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        await query.edit_message_text("Виберіть користувача для видалення:", reply_markup=InlineKeyboardMarkup(rows))
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
        [InlineKeyboardButton("🧪 Тест (4 дні)", callback_data="mode_trial"), InlineKeyboardButton("💳 Підписка (30 днів)", callback_data="mode_subscription")],
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
        # Cancel
        rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")])
        text = (
            "Оберіть користувача зі списку або перегорніть сторінки.\n"
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
        [InlineKeyboardButton("🧪 Тест (4 дні)", callback_data="mode_trial"), InlineKeyboardButton("💳 Підписка (30 днів)", callback_data="mode_subscription")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="admin_cancel")],
    ])
    await update.message.reply_text(
        f"✅ Знайдено: {label} ({target_id})\nСтатус: {status_text}\n\nОберіть режим призначення посилань:",
        reply_markup=kb,
    )
    return CHOOSE_MODE


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
    
    # Start subscription period based on mode selected
    if mode == "trial":
        # Trial mode: 4 days, already set in set_user_links
        await update.message.reply_text(f"✅ Посилання оновлено для {target_id}.\n🧪 Тестовий період на 4 дні активовано.")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🧪 Тестовий період активовано на 4 дні!\n\nПочинаю відстежувати нові оголошення кожні 30 хвилин."
            )
        except Exception:
            pass
    elif mode == "subscription":
        # Subscription mode: start 30-day paid subscription
        um.mark_paid(target_id)
        user_doc = um.db.users.find_one({"user_id": target_id}) or {}
        sub_until = user_doc.get("subscription_expires", "—")
        await update.message.reply_text(f"✅ Посилання оновлено для {target_id}.\n💳 Підписка на 30 днів активована до: {sub_until}")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"💳 Підписку активовано на 30 днів!\nАктивна до: {sub_until}\n\nПочинаю відстежувати нові оголошення кожні 30 хвилин."
            )
        except Exception:
            pass
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
    users = um.get_all_users_for_broadcast()
    if not users:
        await update.message.reply_text("Немає користувачів для розсилки.")
        return ConversationHandler.END
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
            print(f"Failed to send to {user_id}: {e}")
    await update.message.reply_text(
        f"✅ Розсилка завершена!\nУспішно: {success_count}\nПомилок: {fail_count}"
    )
    return ConversationHandler.END


async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text("Скасовано.")
    else:
        await update.message.reply_text("Скасовано.")
    return ConversationHandler.END


def _admin_menu_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("admin", admin_menu),
            # Allow starting the admin conversation from inline buttons shown on /start
            CallbackQueryHandler(admin_menu_cb, pattern=r"^admin_(add_links|broadcast|delete|cancel|paid|cancel_sub|users)$"),
        ],
        states={
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_cb, pattern=r"^admin_(add_links|broadcast|delete|cancel|paid|users)$"),
                CallbackQueryHandler(admin_users_page_cb, pattern=r"^admin_users_page:\d+$"),
                CallbackQueryHandler(user_info_cb, pattern=r"^user_info:.*$"),
                CallbackQueryHandler(noop_cb, pattern=r"^noop:.*$"),
                CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$"),
            ],
            CHOOSE_USER: [
                CallbackQueryHandler(pick_user_cb, pattern=r"^pick_user:.*$"),
                CallbackQueryHandler(admin_list_users_cb, pattern=r"^admin_list_users:\\d+$"),
                CallbackQueryHandler(cancel_subscription_cb, pattern=r"^cancel_sub:.*$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_user_msg),
                CallbackQueryHandler(cancel_cb, pattern=r"^admin_cancel$")
            ],
            CHOOSE_MODE: [CallbackQueryHandler(choose_mode_cb, pattern=r"^mode_(trial|subscription)$")],
            CONFIRM_DELETE: [CallbackQueryHandler(confirm_delete_cb, pattern=r"^del_user:.*$|^admin_cancel$")],
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
    app.add_handler(CallbackQueryHandler(admin_menu_cb, pattern=r"^admin_(add_links|broadcast|delete|cancel|paid|cancel_sub|users)$"))
    app.add_handler(CallbackQueryHandler(pick_user_cb, pattern=r"^pick_user:.*$"))
    app.add_handler(CallbackQueryHandler(admin_list_users_cb, pattern=r"^admin_list_users:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_users_page_cb, pattern=r"^admin_users_page:\d+$"))
    app.add_handler(CallbackQueryHandler(user_info_cb, pattern=r"^user_info:.*$"))
    app.add_handler(CallbackQueryHandler(noop_cb, pattern=r"^noop:.*$"))
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
    if um.delete_user(target_id):
        await query.edit_message_text(f"Користувача {target_id} видалено.")
    else:
        await query.edit_message_text("Не вдалося видалити (можливо, користувача не знайдено або це адмін).")
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


async def user_subscribe_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = query.from_user
    uid = str(u.id)
    # Send separate confirmation (не змінюємо вітальне повідомлення)
    try:
        # Ensure user document exists (edge case: if /start didn't create it)
        if not um.db.users.find_one({"user_id": uid}):
            um.upsert_user(uid, u.username or "", u.first_name or "", u.last_name or "")
        # Mark that user requested subscription (pending approval)
        um.db.users.update_one({"user_id": uid}, {"$set": {"requested_subscription": True}})
        await context.bot.send_message(
            chat_id=uid,
            text=(
                "🎉 Ти на кроці до своєї квартири!\n\n"
                "1️⃣ Напиши адміну до 4 міст, де хочеш шукати житло.\n"
                "2️⃣ Отримай безкоштовний тест на 4 дні.\n"
                "3️⃣ Далі — лише 20€/місяць, щоб отримувати найсвіжіші оголошення першим!\n\n"
                "📩 Адмін - @reeziat"
            ),
            reply_markup=_back_to_menu_keyboard(),
        )
    except Exception:
        pass
    # notify admins
    if not _admin_ids:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Схвалити", callback_data=f"admin_inline_approve:{uid}")],
        [InlineKeyboardButton("❌ Відхилити", callback_data=f"admin_inline_decline:{uid}")],
    ])
    text = (
        f"Нова заявка на підписку\n"
        f"ID: {uid}\nUsername: @{u.username if u.username else '—'}\n"
        f"Ім'я: {u.first_name or ''} {u.last_name or ''}"
    )
    for aid in _admin_ids:
        try:
            await context.bot.send_message(chat_id=aid, text=text, reply_markup=kb)
        except Exception:
            pass


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
    um.approve_user(uid)
    # Mark awaiting payment and clear request flag
    um.db.users.update_one({"user_id": uid}, {"$set": {"awaiting_payment": True}, "$unset": {"requested_subscription": ""}})
    await query.edit_message_text(f"Користувача {uid} схвалено. Очікує оплату.")
    # Notify user about approval and payment step
    try:
        await context.bot.send_message(chat_id=uid, text=(
            "✅ Заявку схвалено. Доступ активується після оплати.\n"
            "Після підтвердження оплати адміністратором підписка стартує на 30 днів."
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


# ---- User menu handlers ----
async def user_support_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Import support contact from config was done at top; fallback if empty
    contact = SUPPORT_CONTACT or "@admin"
    try:
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=f"🛠️ Техпідтримка\n\nЗв'яжіться з адміністратором: {contact}",
            reply_markup=_back_to_menu_keyboard(),
        )
    except Exception:
        pass


async def user_sub_info_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = str(q.from_user.id)
    u = um.db.users.find_one({"user_id": uid})
    status = (u or {}).get("status")
    date_activated = (u or {}).get("date_activated")
    subscription_expires = (u or {}).get("subscription_expires")
    requested = (u or {}).get("requested_subscription")
    now_iso = datetime.utcnow().isoformat()
    active_valid = (
        status == "active" and subscription_expires and subscription_expires >= now_iso
    )
    # Format date as DD.MM.YYYY for clarity
    def _fmt_date(iso: str) -> str:
        try:
            from datetime import datetime as _dt
            dt = _dt.fromisoformat(iso)
            return dt.strftime("%d.%m.%Y")
        except Exception:
            return iso
    if active_valid and subscription_expires:
        msg = f"📅 Підписка активна до: {_fmt_date(subscription_expires)}"
    elif requested:
        msg = "⏳ Заявка на підписку очікує підтвердження адміністратора."
    else:
        msg = "❌ Ви ще не активовані."
    try:
        await context.bot.send_message(chat_id=q.message.chat_id, text=msg, reply_markup=_back_to_menu_keyboard())
    except Exception:
        pass


async def user_back_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        uid = str(q.from_user.id)
        u = um.db.users.find_one({"user_id": uid})
        status = (u or {}).get("status")
        subscription_expires = (u or {}).get("subscription_expires")
        now_iso = datetime.utcnow().isoformat()
        active_valid = status == "active" and subscription_expires and subscription_expires >= now_iso
        if active_valid:
            # For active users we can show compact menu
            await context.bot.send_message(chat_id=q.message.chat_id, text="Головне меню:", reply_markup=_user_menu_keyboard())
        else:
            # Re-send full welcome while not active
            await context.bot.send_message(chat_id=q.message.chat_id, text=WELCOME_TEXT, reply_markup=_user_menu_keyboard())
    except Exception:
        pass
