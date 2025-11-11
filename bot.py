#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot для управління підписками та взаємодії з користувачами
Надає інтерфейс для управління підписками на парсер оголошень
"""

import logging
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Завантажуємо змінні середовища
load_dotenv()

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class SubscriptionBot:
    """Клас для управління Telegram ботом з підписками"""
    
    def __init__(self, config_file: str = "config.json"):
        """Ініціалізація бота"""
        self.config = self.load_config(config_file)
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or self.config.get('telegram', {}).get('bot_token')
        self.db_path = self.config.get('database', {}).get('path', 'data/bot_users.db')
        self.admin_ids = self.config.get('bot', {}).get('admin_ids', [])
        
        # Створюємо папку для бази даних якщо не існує
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else 'data', exist_ok=True)
        
        # Ініціалізуємо базу даних
        self.init_database()
        
    def load_config(self, config_file: str) -> Dict:
        """Завантаження конфігурації з файлу"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Файл конфігурації {config_file} не знайдено, використовуємо значення за замовчуванням")
            return {}
    
    def init_database(self):
        """Ініціалізація бази даних для користувачів"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Створюємо таблицю користувачів
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                subscription_start_date TEXT,
                subscription_end_date TEXT,
                is_trial INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_interaction TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Створюємо таблицю історії підписок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscription_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                date TEXT DEFAULT CURRENT_TIMESTAMP,
                details TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("База даних ініціалізована")
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Отримання інформації про користувача"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def create_or_update_user(self, user_id: int, username: str = None, 
                              first_name: str = None, last_name: str = None):
        """Створення або оновлення користувача"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Перевіряємо чи існує користувач
        existing_user = self.get_user(user_id)
        
        if existing_user:
            # Оновлюємо дані користувача
            cursor.execute('''
                UPDATE users 
                SET username = ?, first_name = ?, last_name = ?, last_interaction = ?
                WHERE user_id = ?
            ''', (username, first_name, last_name, datetime.now().isoformat(), user_id))
        else:
            # Створюємо нового користувача
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
        
        conn.commit()
        conn.close()
    
    def start_trial_subscription(self, user_id: int):
        """Запуск пробного періоду на 14 днів"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        start_date = datetime.now()
        end_date = start_date + timedelta(days=14)
        
        cursor.execute('''
            UPDATE users 
            SET subscription_start_date = ?, 
                subscription_end_date = ?,
                is_trial = 1,
                is_active = 1
            WHERE user_id = ?
        ''', (start_date.isoformat(), end_date.isoformat(), user_id))
        
        # Додаємо запис в історію
        cursor.execute('''
            INSERT INTO subscription_history (user_id, action, details)
            VALUES (?, ?, ?)
        ''', (user_id, 'trial_started', '14 днів безкоштовного пробного періоду'))
        
        conn.commit()
        conn.close()
        logger.info(f"Користувач {user_id} розпочав пробний період")
    
    def is_user_subscribed(self, user_id: int) -> bool:
        """Перевірка чи користувач має активну підписку"""
        user = self.get_user(user_id)
        if not user or not user['is_active']:
            return False
        
        # Перевіряємо чи не закінчилася підписка
        if user['subscription_end_date']:
            end_date = datetime.fromisoformat(user['subscription_end_date'])
            if datetime.now() > end_date:
                # Підписка закінчилася, деактивуємо
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET is_active = 0 WHERE user_id = ?', (user_id,))
                conn.commit()
                conn.close()
                return False
        
        return True
    
    def is_admin(self, user_id: int) -> bool:
        """Перевірка чи користувач є адміністратором"""
        return user_id in self.admin_ids
    
    # === Обробники команд ===
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /start"""
        user = update.effective_user
        user_id = user.id
        
        # Створюємо або оновлюємо користувача
        self.create_or_update_user(user_id, user.username, user.first_name, user.last_name)
        
        # Привітальне повідомлення
        welcome_message = (
            "🏠 Пошук квартири в Німеччині без стресу\n\n"
            "Втомився щодня оновлювати Kleinanzeigen та Immowelt і не "
            "отримувати відповідей?\n"
            "Наш бот зробить це за тебе!\n\n"
            "✅ Автоматично сканує Kleinanzeigen і Immowelt кожні 30 хвилин.\n"
            "✅ Надсилає найновіші оголошення першим, ще до того, як "
            "інші їх побачать.\n"
            "✅ Пиши власникам серед перших — і збільшуй свої шанси "
            "отримати квартиру!\n\n"
            "🎁 Спробуй безкоштовно 4 дні, потім — лише 20€/місяць.\n\n"
            "🚀 Натисни «РОЗПОЧАТИ» і знайди квартиру швидше за інших!"
        )
        
        # Створюємо клавіатуру з кнопками (БЕЗ кнопки дати підписки)
        keyboard = [
            [InlineKeyboardButton("🔧 Технідтримка", callback_data="support")],
            [InlineKeyboardButton("🔔 Розпочати", callback_data="start_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    
    async def cabinet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /cabinet - особистий кабінет"""
        user_id = update.effective_user.id
        user = self.get_user(user_id)
        
        if not user:
            await update.message.reply_text("❌ Користувач не знайдений. Натисніть /start")
            return
        
        # Формуємо повідомлення особистого кабінету
        is_subscribed = self.is_user_subscribed(user_id)
        
        if is_subscribed:
            subscription_info = self._format_subscription_info(user)
            message = f"👤 Особистий кабінет\n\n{subscription_info}"
            
            # Клавіатура для підписаних користувачів (З кнопкою дати підписки)
            keyboard = [
                [InlineKeyboardButton("📅 Дата початку підписки", callback_data="subscription_date")],
                [InlineKeyboardButton("🔧 Технідтримка", callback_data="support")],
                [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
            ]
        else:
            message = (
                "👤 Особистий кабінет\n\n"
                "❌ У вас немає активної підписки\n\n"
                "Натисніть кнопку нижче, щоб розпочати безкоштовний пробний період на 14 днів!"
            )
            keyboard = [
                [InlineKeyboardButton("🔔 Розпочати", callback_data="start_subscription")],
                [InlineKeyboardButton("🔧 Технідтримка", callback_data="support")],
                [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник команди /admin - адміністративне меню"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас немає доступу до адміністративного меню")
            return
        
        # Отримуємо статистику
        stats = self._get_stats()
        
        message = (
            "🔧 Адміністративне меню\n\n"
            f"📊 Статистика:\n"
            f"• Всього користувачів: {stats['total_users']}\n"
            f"• Активних підписок: {stats['active_subscriptions']}\n"
            f"• Пробних підписок: {stats['trial_subscriptions']}\n"
            f"• Нових сьогодні: {stats['new_today']}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("📊 Детальна статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Список користувачів", callback_data="admin_users")],
            [InlineKeyboardButton("📢 Розсилка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    # === Обробники callback-запитів ===
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обробник натискань на кнопки"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        callback_data = query.data
        
        if callback_data == "support":
            await self._handle_support(query)
        
        elif callback_data == "start_subscription":
            await self._handle_start_subscription(query, user_id)
        
        elif callback_data == "subscription_date":
            await self._handle_subscription_date(query, user_id)
        
        elif callback_data == "main_menu":
            await self._handle_main_menu(query)
        
        elif callback_data == "admin_stats":
            await self._handle_admin_stats(query, user_id)
        
        elif callback_data == "admin_users":
            await self._handle_admin_users(query, user_id)
        
        elif callback_data == "admin_broadcast":
            await self._handle_admin_broadcast(query, user_id)
        
        elif callback_data == "cabinet":
            await self._handle_cabinet(query, user_id)
        
        elif callback_data == "admin_menu":
            await self._handle_admin_menu(query, user_id)
    
    async def _handle_support(self, query):
        """Обробка натискання кнопки технічної підтримки"""
        message = (
            "🔧 Технічна підтримка\n\n"
            "З питань технічної підтримки звертайтеся:\n"
            "📧 Email: support@example.com\n"
            "💬 Telegram: @support_username\n\n"
            "Ми відповідаємо протягом 24 годин."
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def _handle_start_subscription(self, query, user_id: int):
        """Обробка початку підписки"""
        # Перевіряємо чи вже є підписка
        if self.is_user_subscribed(user_id):
            await query.edit_message_text("✅ У вас вже є активна підписка!")
            return
        
        # Запускаємо пробний період
        self.start_trial_subscription(user_id)
        
        message = (
            "🎉 Вітаємо! Ваш 14-денний пробний період активовано!\n\n"
            "Тепер ви будете отримувати сповіщення про нові оголошення "
            "кожні 30 хвилин.\n\n"
            "📅 Підписка діє до: " + self._get_subscription_end_date(user_id) + "\n\n"
            "Перейдіть в особистий кабінет (/cabinet) щоб переглянути деталі підписки."
        )
        
        keyboard = [
            [InlineKeyboardButton("👤 Особистий кабінет", callback_data="cabinet")],
            [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def _handle_subscription_date(self, query, user_id: int):
        """Обробка перегляду дати підписки"""
        user = self.get_user(user_id)
        
        if not user or not user['subscription_start_date']:
            await query.edit_message_text("❌ Інформація про підписку не знайдена")
            return
        
        message = self._format_subscription_info(user)
        
        keyboard = [
            [InlineKeyboardButton("👤 Особистий кабінет", callback_data="cabinet")],
            [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def _handle_main_menu(self, query):
        """Обробка повернення до головного меню"""
        welcome_message = (
            "🏠 Пошук квартири в Німеччині без стресу\n\n"
            "Виберіть опцію з меню:"
        )
        
        keyboard = [
            [InlineKeyboardButton("👤 Особистий кабінет", callback_data="cabinet")],
            [InlineKeyboardButton("🔧 Технідтримка", callback_data="support")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(welcome_message, reply_markup=reply_markup)
    
    async def _handle_admin_stats(self, query, user_id: int):
        """Обробка перегляду детальної статистики (адмін)"""
        if not self.is_admin(user_id):
            await query.answer("❌ Недостатньо прав", show_alert=True)
            return
        
        stats = self._get_detailed_stats()
        
        message = (
            "📊 Детальна статистика\n\n"
            f"👥 Користувачі:\n"
            f"• Всього: {stats['total_users']}\n"
            f"• Нових сьогодні: {stats['new_today']}\n"
            f"• Нових цього тижня: {stats['new_week']}\n"
            f"• Нових цього місяця: {stats['new_month']}\n\n"
            f"💰 Підписки:\n"
            f"• Активних: {stats['active_subscriptions']}\n"
            f"• Пробних: {stats['trial_subscriptions']}\n"
            f"• Оплачених: {stats['paid_subscriptions']}\n"
            f"• Закінчилися сьогодні: {stats['expiring_today']}\n"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Адмін меню", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def _handle_admin_users(self, query, user_id: int):
        """Обробка перегляду списку користувачів (адмін)"""
        if not self.is_admin(user_id):
            await query.answer("❌ Недостатньо прав", show_alert=True)
            return
        
        # TODO: Реалізувати постраничний перегляд користувачів
        message = "👥 Список користувачів\n\n(Функція в розробці)"
        
        keyboard = [[InlineKeyboardButton("🔙 Адмін меню", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def _handle_admin_broadcast(self, query, user_id: int):
        """Обробка розсилки повідомлень (адмін)"""
        if not self.is_admin(user_id):
            await query.answer("❌ Недостатньо прав", show_alert=True)
            return
        
        # TODO: Реалізувати розсилку
        message = "📢 Розсилка повідомлень\n\n(Функція в розробці)"
        
        keyboard = [[InlineKeyboardButton("🔙 Адмін меню", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def _handle_cabinet(self, query, user_id: int):
        """Обробка переходу в особистий кабінет через callback"""
        user = self.get_user(user_id)
        
        if not user:
            await query.edit_message_text("❌ Користувач не знайдений. Натисніть /start")
            return
        
        # Формуємо повідомлення особистого кабінету
        is_subscribed = self.is_user_subscribed(user_id)
        
        if is_subscribed:
            subscription_info = self._format_subscription_info(user)
            message = f"👤 Особистий кабінет\n\n{subscription_info}"
            
            # Клавіатура для підписаних користувачів (З кнопкою дати підписки)
            keyboard = [
                [InlineKeyboardButton("📅 Дата початку підписки", callback_data="subscription_date")],
                [InlineKeyboardButton("🔧 Технідтримка", callback_data="support")],
                [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
            ]
        else:
            message = (
                "👤 Особистий кабінет\n\n"
                "❌ У вас немає активної підписки\n\n"
                "Натисніть кнопку нижче, щоб розпочати безкоштовний пробний період на 14 днів!"
            )
            keyboard = [
                [InlineKeyboardButton("🔔 Розпочати", callback_data="start_subscription")],
                [InlineKeyboardButton("🔧 Технідтримка", callback_data="support")],
                [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def _handle_admin_menu(self, query, user_id: int):
        """Обробка переходу в адмін меню через callback"""
        if not self.is_admin(user_id):
            await query.answer("❌ Недостатньо прав", show_alert=True)
            return
        
        # Отримуємо статистику
        stats = self._get_stats()
        
        message = (
            "🔧 Адміністративне меню\n\n"
            f"📊 Статистика:\n"
            f"• Всього користувачів: {stats['total_users']}\n"
            f"• Активних підписок: {stats['active_subscriptions']}\n"
            f"• Пробних підписок: {stats['trial_subscriptions']}\n"
            f"• Нових сьогодні: {stats['new_today']}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("📊 Детальна статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Список користувачів", callback_data="admin_users")],
            [InlineKeyboardButton("📢 Розсилка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🔙 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    # === Допоміжні методи ===
    
    def _format_subscription_info(self, user: Dict) -> str:
        """Форматування інформації про підписку"""
        if not user['subscription_start_date']:
            return "❌ Немає активної підписки"
        
        start_date = datetime.fromisoformat(user['subscription_start_date'])
        end_date = datetime.fromisoformat(user['subscription_end_date']) if user['subscription_end_date'] else None
        
        subscription_type = "🎁 Пробна" if user['is_trial'] else "💎 Оплачена"
        status = "✅ Активна" if user['is_active'] else "❌ Неактивна"
        
        info = (
            f"📋 Інформація про підписку\n\n"
            f"Тип: {subscription_type}\n"
            f"Статус: {status}\n"
            f"📅 Початок: {start_date.strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        if end_date:
            days_left = (end_date - datetime.now()).days
            info += f"📅 Закінчується: {end_date.strftime('%d.%m.%Y %H:%M')}\n"
            info += f"⏰ Залишилось днів: {days_left}\n"
        
        return info
    
    def _get_subscription_end_date(self, user_id: int) -> str:
        """Отримання дати закінчення підписки"""
        user = self.get_user(user_id)
        if user and user['subscription_end_date']:
            end_date = datetime.fromisoformat(user['subscription_end_date'])
            return end_date.strftime('%d.%m.%Y')
        return "N/A"
    
    def _get_stats(self) -> Dict:
        """Отримання базової статистики"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
        active_subscriptions = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1 AND is_trial = 1')
        trial_subscriptions = cursor.fetchone()[0]
        
        today = datetime.now().date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM users WHERE DATE(created_at) = ?', (today,))
        new_today = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_users': total_users,
            'active_subscriptions': active_subscriptions,
            'trial_subscriptions': trial_subscriptions,
            'new_today': new_today
        }
    
    def _get_detailed_stats(self) -> Dict:
        """Отримання детальної статистики"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = self._get_stats()
        
        # Нові користувачі за тиждень
        week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM users WHERE DATE(created_at) >= ?', (week_ago,))
        stats['new_week'] = cursor.fetchone()[0]
        
        # Нові користувачі за місяць
        month_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM users WHERE DATE(created_at) >= ?', (month_ago,))
        stats['new_month'] = cursor.fetchone()[0]
        
        # Оплачені підписки
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1 AND is_trial = 0')
        stats['paid_subscriptions'] = cursor.fetchone()[0]
        
        # Підписки що закінчуються сьогодні
        today = datetime.now().date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM users WHERE DATE(subscription_end_date) = ?', (today,))
        stats['expiring_today'] = cursor.fetchone()[0]
        
        conn.close()
        
        return stats
    
    def run(self):
        """Запуск бота"""
        if not self.bot_token:
            logger.error("Bot token не налаштований. Перевірте config.json або .env файл")
            return
        
        # Створюємо додаток
        application = Application.builder().token(self.bot_token).build()
        
        # Додаємо обробники команд
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("cabinet", self.cabinet_command))
        application.add_handler(CommandHandler("admin", self.admin_command))
        
        # Додаємо обробник callback-запитів від кнопок
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Запускаємо бота
        logger.info("Бот запущено")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Головна функція"""
    bot = SubscriptionBot()
    bot.run()


if __name__ == '__main__':
    main()
