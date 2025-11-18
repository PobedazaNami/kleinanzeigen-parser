#!/usr/bin/env python3
"""
Base Parser - Базовый класс для всех парсеров
Содержит общую функциональность для парсинга объявлений
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import logging
import sqlite3
import re
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
import hashlib
import traceback
from dotenv import load_dotenv
import requests as sync_requests


class BaseParser:
    """Базовый класс для парсеров объявлений"""
    
    def __init__(self, config_file: str = "config.json", parser_name: str = "base"):
        """Инициализация базового парсера"""
        # Загружаем .env файл если он существует
        load_dotenv()
        
        self.parser_name = parser_name
        self.config = self.load_config(config_file)
        self._override_config_with_env()
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_path, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(f"{__name__}.{parser_name}")
        
        # Создаем HTTP сессию
        self.session = requests.Session()
        self._setup_session_headers()
        
        # Инициализация базы данных
        self.init_database()
        
        # Счетчики для мониторинга
        self.last_successful_run = None
        self.consecutive_failures = 0
        self.last_listings_found = 0
        self.total_runs = 0
        
    def _setup_session_headers(self):
        """Настройка заголовков HTTP сессии"""
        import random
        
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'
        ]
        
        selected_ua = random.choice(user_agents)
        
        self.session.headers.update({
            'User-Agent': selected_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1'
        })
        
    def load_config(self, config_file: str) -> Dict:
        """Загрузка конфигурации из файла"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.error(f"Файл конфигурации {config_file} не найден") if hasattr(self, 'logger') else None
            return {
                "search_urls": [],
                "filters": {
                    "max_price": 1500,
                    "min_size": 30,
                    "max_size": 150
                },
                "telegram": {
                    "bot_token": "",
                    "chat_id": ""
                },
                "update_interval": 30
            }

    def _override_config_with_env(self):
        """Переопределяет конфигурацию переменными окружения"""
        # Telegram настройки
        if os.getenv('TELEGRAM_BOT_TOKEN'):
            self.config['telegram']['bot_token'] = os.getenv('TELEGRAM_BOT_TOKEN')
        if os.getenv('TELEGRAM_CHAT_ID'):
            self.config['telegram']['chat_id'] = os.getenv('TELEGRAM_CHAT_ID')
            
        # Search URLs
        if os.getenv('SEARCH_URLS'):
            self.config['search_urls'] = os.getenv('SEARCH_URLS').split(';')
            
        # Пути к файлам
        if os.getenv('DATABASE_PATH'):
            self.database_path = os.getenv('DATABASE_PATH')
        else:
            if os.path.exists('/app'):  # Docker
                self.database_path = '/app/data/listings.db'
            else:  # Локальная разработка
                os.makedirs('data', exist_ok=True)
                self.database_path = 'data/listings.db'
            
        if os.getenv('LOG_PATH'):
            self.log_path = os.getenv('LOG_PATH')
        else:
            if os.path.exists('/app'):  # Docker
                self.log_path = f'/app/logs/{self.parser_name}_parser.log'
            else:  # Локальная разработка
                os.makedirs('logs', exist_ok=True)
                self.log_path = f'logs/{self.parser_name}_parser.log'
    
    def init_database(self):
        """Инициализация SQLite базы данных"""
        self.conn = sqlite3.connect(self.database_path)
        self.cursor = self.conn.cursor()
        
        # Создание таблицы для хранения объявлений
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                price INTEGER,
                size INTEGER,
                rooms TEXT,
                location TEXT,
                description TEXT,
                url TEXT NOT NULL,
                date_posted TEXT,
                date_found TEXT,
                notified BOOLEAN DEFAULT FALSE,
                hash TEXT UNIQUE
            )
        ''')
        
        # Добавляем колонку date_posted если её нет
        try:
            self.cursor.execute('ALTER TABLE listings ADD COLUMN date_posted TEXT')
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        self.conn.commit()
    
    def send_telegram_sync(self, message: str, parse_mode: str = 'Markdown', disable_web_page_preview: bool = False, 
                          link_preview_options: Optional[Dict] = None):
        """Синхронная отправка сообщения в Telegram через HTTP API"""
        if not self.config.get('telegram', {}).get('bot_token') or not self.config.get('telegram', {}).get('chat_id'):
            return False
            
        try:
            bot_token = self.config['telegram']['bot_token']
            chat_id = self.config['telegram']['chat_id']
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            data = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            
            # Use newer link_preview_options if provided, otherwise fall back to disable_web_page_preview
            if link_preview_options is not None:
                data['link_preview_options'] = json.dumps(link_preview_options)
            else:
                data['disable_web_page_preview'] = disable_web_page_preview
            
            response = sync_requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при синхронной отправке в Telegram: {e}")
            return False
    
    def get_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        """Получение и парсинг HTML страницы"""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=10)
                
                if response.status_code >= 400:
                    error_msg = f"HTTP {response.status_code} для {url}"
                    self.logger.warning(error_msg)
                    if attempt == retries - 1:
                        self.send_error_notification(error_msg, f"HTTP {response.status_code}")
                
                response.raise_for_status()
                
                if response.encoding != 'utf-8':
                    response.encoding = 'utf-8'
                
                if self.check_for_blocking(response.text, url):
                    return None
                
                if len(response.text) < 1000:
                    self.logger.warning(f"Подозрительно короткий ответ ({len(response.text)} символов)")
                    if attempt == retries - 1:
                        self.send_error_notification(f"Короткий ответ от {url}", "ПОДОЗРИТЕЛЬНЫЙ ОТВЕТ")
                
                return BeautifulSoup(response.text, 'html.parser')
            
            except requests.exceptions.Timeout:
                error_msg = f"Таймаут при загрузке {url} (попытка {attempt + 1})"
                self.logger.warning(error_msg)
                if attempt == retries - 1:
                    self.send_error_notification(error_msg, "ТАЙМАУТ")
                    
            except requests.exceptions.ConnectionError:
                error_msg = f"Ошибка соединения с {url} (попытка {attempt + 1})"
                self.logger.warning(error_msg)
                if attempt == retries - 1:
                    self.send_error_notification(error_msg, "ОШИБКА СОЕДИНЕНИЯ")
                    
            except Exception as e:
                error_msg = f"Ошибка при загрузке {url}: {e}"
                self.logger.error(error_msg)
                if attempt == retries - 1:
                    self.send_error_notification(error_msg, "ОШИБКА")
                
            if attempt < retries - 1:
                sleep_time = 2 ** attempt
                self.logger.info(f"Ожидание {sleep_time} сек. перед повторной попыткой...")
                time.sleep(sleep_time)
        
        return None
    
    def check_for_blocking(self, response_text: str, url: str) -> bool:
        """Проверка на блокировку сайтом"""
        blocking_indicators = [
            "access denied",
            "blocked",
            "captcha",
            "bot detection",
            "rate limit", 
            "too many requests",
            "403 forbidden",
            "cloudflare",
            "you are being rate limited",
            "your request has been blocked"
        ]
        
        text_lower = response_text.lower()
        
        if 'robots" content="index' in text_lower:
            pass
        elif "robot" in text_lower and "robots.txt" not in text_lower:
            return True
        
        for indicator in blocking_indicators:
            if indicator in text_lower:
                self.logger.warning(f"Обнаружен индикатор блокировки: {indicator}")
                self.send_status_notification("BLOCKED", f"Индикатор: {indicator}, URL: {url}")
                return True
                
        return False
    
    def check_filters(self, listing: Dict) -> bool:
        """Проверка соответствия объявления фильтрам"""
        filters = self.config.get('filters', {})
        
        if filters.get('max_price') and listing.get('price'):
            if listing['price'] > filters['max_price']:
                return False
        
        if filters.get('min_size') and listing.get('size'):
            if listing['size'] < filters['min_size']:
                return False
        
        if filters.get('max_size') and listing.get('size'):
            if listing['size'] > filters['max_size']:
                return False
        
        excluded_words = filters.get('excluded_words', [])
        if excluded_words:
            text = f"{listing.get('title', '')} {listing.get('description', '')}".lower()
            for word in excluded_words:
                if word.lower() in text:
                    return False
        
        return True
    
    def save_listing(self, listing: Dict) -> bool:
        """Сохранение объявления в базу данных"""
        try:
            self.cursor.execute('SELECT notified FROM listings WHERE id = ? OR hash = ?', 
                              (listing['id'], listing['hash']))
            existing = self.cursor.fetchone()
            
            if existing:
                return not existing[0]
            
            self.cursor.execute('''
                INSERT INTO listings 
                (id, title, price, size, rooms, location, description, url, date_posted, date_found, hash, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                listing['id'], listing['title'], listing['price'], listing['size'],
                listing['rooms'], listing['location'], listing['description'],
                listing['url'], listing['date_posted'], listing['date_found'], listing['hash'], False
            ))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении объявления: {e}")
            return False
    
    def send_telegram_notification(self, listing: Dict):
        """Отправка уведомления в Telegram"""
        if not self.config.get('telegram', {}).get('chat_id'):
            self.logger.warning("Telegram не настроен")
            return
        
        try:
            message = f"🏠 *Новая квартира найдена!*\n\n"
            message += f"📝 *{listing['title']}*\n"
            message += f"💰 Цена: *{listing['price']}€*\n" if listing['price'] else ""
            message += f"📐 Размер: *{listing['size']} м²*\n" if listing['size'] else ""
            message += f"🏠 Комнат: *{listing['rooms']}*\n" if listing['rooms'] else ""
            message += f"📍 Местоположение: *{listing['location']}*\n" if listing['location'] else ""
            message += f"\n🔗 [Посмотреть объявление]({listing['url']})"
            
            if listing.get('description'):
                message += f"\n\n📄 Описание:\n{listing['description'][:200]}..."
            
            # Use link_preview_options to enable large media previews (for videos, images)
            link_preview_opts = {
                'is_disabled': False,
                'prefer_large_media': True,
                'show_above_text': True
            }
            
            self.send_telegram_sync(message, parse_mode='Markdown', link_preview_options=link_preview_opts)
            
            self.cursor.execute(
                'UPDATE listings SET notified = TRUE WHERE id = ?',
                (listing['id'],)
            )
            self.conn.commit()
            
            self.logger.info(f"Уведомление отправлено для: {listing['title']}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при отправке уведомления: {e}")
            self.send_error_notification(f"Ошибка при отправке уведомления: {e}")
    
    def send_error_notification(self, error_message: str, error_type: str = "ОШИБКА"):
        """Отправка уведомления об ошибке в Telegram"""
        if not self.config.get('telegram', {}).get('chat_id'):
            return
        
        try:
            message = f"🚨 *{error_type} ПАРСЕРА {self.parser_name.upper()}*\n\n"
            message += f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            message += f"📝 Описание: `{error_message}`\n"
            
            self.send_telegram_sync(message, parse_mode='Markdown')
            
            self.logger.info(f"Отправлено уведомление об ошибке: {error_message}")
            
        except Exception as e:
            self.logger.error(f"Не удалось отправить уведомление об ошибке: {e}")
    
    def send_status_notification(self, status_type: str, details: str = ""):
        """Отправка уведомлений о статусе парсера"""
        if not self.config.get('telegram', {}).get('chat_id'):
            return
        
        try:
            if status_type == "NO_RESULTS":
                message = f"🔍 *МОНИТОРИНГ ПАРСЕРА {self.parser_name.upper()}*\n\n"
                message += f"⚠️ Уже 30 минут не найдено новых объявлений\n"
                message += f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                
            elif status_type == "BLOCKED":
                message = f"🚫 *САЙТ ЗАБЛОКИРОВАЛ ПАРСЕР {self.parser_name.upper()}*\n\n"
                message += f"⚠️ Возможная блокировка доступа\n"
                message += f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                message += f"📝 Детали: {details}\n"
                
            elif status_type == "RECOVERY":
                message = f"✅ *ПАРСЕР {self.parser_name.upper()} ВОССТАНОВЛЕН*\n\n"
                message += f"🎉 Работа парсера возобновлена!\n"
                message += f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                
            else:
                message = f"📊 *СТАТУС ПАРСЕРА {self.parser_name.upper()}*\n\n{details}"
            
            self.send_telegram_sync(message, parse_mode='Markdown')
            
        except Exception as e:
            self.logger.error(f"Ошибка при отправке статусного уведомления: {e}")
    
    def is_listing_from_today(self, listing_date: Optional[datetime]) -> bool:
        """Проверка, что объявление опубликовано недавно"""
        if not listing_date:
            return False
        
        date_config = self.config.get('date_filtering', {})
        only_today = date_config.get('only_today', True)
        max_days_old = date_config.get('max_days_old', 1)
        
        today = datetime.now().date()
        listing_day = listing_date.date()
        
        if only_today:
            return listing_day == today
        else:
            days_diff = (today - listing_day).days
            return days_diff <= max_days_old
    
    # Методы, которые должны быть переопределены в дочерних классах
    def extract_listing_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Извлечение ссылок на объявления - должен быть переопределен"""
        raise NotImplementedError("Метод должен быть реализован в дочернем классе")
    
    def extract_listing_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Извлечение даты публикации - должен быть переопределен"""
        raise NotImplementedError("Метод должен быть реализован в дочернем классе")
    
    def extract_listing_data(self, soup: BeautifulSoup, url: str) -> Optional[Dict]:
        """Извлечение данных объявления - должен быть переопределен"""
        raise NotImplementedError("Метод должен быть реализован в дочернем классе")
    
    def get_initial_cookies(self):
        """Получение начальных cookies - может быть переопределен"""
        return True
    
    def parse_listings(self):
        """Основной метод парсинга"""
        start_time = datetime.now()
        self.total_runs += 1
        
        self.logger.info(f"Начинаем парсинг {self.parser_name} (запуск #{self.total_runs})")
        
        self.get_initial_cookies()
        
        new_listings_count = 0
        total_processed = 0
        errors_count = 0
        skipped_by_date_count = 0
        
        try:
            for search_url in self.config.get('search_urls', []):
                self.logger.info(f"Парсинг страницы: {search_url}")
                
                soup = self.get_page(search_url)
                if not soup:
                    errors_count += 1
                    continue
                
                listing_links = self.extract_listing_links(soup, search_url)
                
                if not listing_links:
                    self.logger.warning(f"Не найдено ссылок на объявления")
                    continue
                
                max_listings = self.config.get('settings', {}).get('max_listings_per_run', 50)
                request_delay = self.config.get('settings', {}).get('request_delay', 2)
                
                for i, link in enumerate(listing_links[:max_listings]):
                    total_processed += 1
                    self.logger.info(f"Обрабатываем {i+1}/{min(len(listing_links), max_listings)}: {link}")
                    
                    try:
                        listing_soup = self.get_page(link)
                        if not listing_soup:
                            errors_count += 1
                            continue
                        
                        listing_data = self.extract_listing_data(listing_soup, link)
                        if listing_data is None:
                            errors_count += 1
                            continue
                        elif listing_data == "SKIPPED_BY_DATE":
                            skipped_by_date_count += 1
                            continue
                        
                        if not self.check_filters(listing_data):
                            self.logger.info(f"Не прошло фильтры: {listing_data['title']}")
                            continue
                        
                        is_new = self.save_listing(listing_data)
                        if is_new:
                            new_listings_count += 1
                            self.logger.info(f"Новое объявление: {listing_data['title']}")
                            self.send_telegram_notification(listing_data)
                        
                    except Exception as e:
                        errors_count += 1
                        error_msg = f"Ошибка при обработке {link}: {e}"
                        self.logger.error(error_msg)
                        self.send_error_notification(error_msg, "ОШИБКА ПАРСИНГА")
                    
                    time.sleep(request_delay)
            
            duration = datetime.now() - start_time
            self.last_listings_found = new_listings_count
            
            if new_listings_count > 0:
                self.last_successful_run = datetime.now().isoformat()
                self.consecutive_failures = 0
            else:
                self.consecutive_failures += 1
            
            self.logger.info(f"Парсинг завершен за {duration.total_seconds():.1f}сек. "
                           f"Новых: {new_listings_count}, "
                           f"Обработано: {total_processed}, "
                           f"Пропущено по дате: {skipped_by_date_count}, "
                           f"Ошибок: {errors_count}")
                           
        except Exception as e:
            self.consecutive_failures += 1
            error_details = f"{str(e)}\n\n{traceback.format_exc()}"
            self.logger.error(f"Критическая ошибка: {error_details}")
            self.send_error_notification(f"Критическая ошибка: {e}", "КРИТИЧЕСКАЯ ОШИБКА")
    
    def run_once(self):
        """Выполнить один цикл парсинга"""
        try:
            self.logger.info(f"Запуск одного цикла парсинга {self.parser_name}...")
            self.parse_listings()
            self.logger.info("Цикл парсинга завершен")
        except Exception as e:
            self.logger.error(f"Ошибка во время парсинга: {e}")
            raise
    
    def __del__(self):
        """Деструктор для закрытия соединения с БД"""
        if hasattr(self, 'conn'):
            self.conn.close()
