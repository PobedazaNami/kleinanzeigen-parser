#!/usr/bin/env python3
"""
Kleinanzeigen Parser для квартир в аренду
Парсит объявления с Kleinanzeigen.de и отправляет уведомления в Telegram
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
import schedule
import telegram
from telegram import Bot
import traceback
import sys
from dotenv import load_dotenv


class KleinanzeigenParser:
    """Основной класс для парсинга объявлений с Kleinanzeigen"""
    
    def __init__(self, config_file: str = "config.json"):
        """Инициализация парсера с конфигурацией"""
        # Загружаем .env файл если он существует
        load_dotenv()
        
        self.config = self.load_config(config_file)
        # Переопределяем конфиг переменными окружения
        self._override_config_with_env()
        
        # Настройка логирования (после установки путей)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_path, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        self.session = requests.Session()
        # Более актуальный User-Agent
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'
        ]
        
        import random
        selected_ua = random.choice(user_agents)
        
        self.session.headers.update({
            'User-Agent': selected_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        })
        
        # Инициализация базы данных
        self.init_database()
        
        # Инициализация Telegram Bot
        self.bot = Bot(token=self.config['telegram']['bot_token']) if self.config.get('telegram', {}).get('bot_token') else None
        
        # Счетчики для мониторинга
        self.last_successful_run = None
        self.consecutive_failures = 0
        self.last_listings_found = 0
        self.total_runs = 0
        
    def load_config(self, config_file: str) -> Dict:
        """Загрузка конфигурации из файла"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.error(f"Файл конфигурации {config_file} не найден")
            # Возвращаем базовую конфигурацию по умолчанию
            return {
                "search_urls": [
                    "https://www.kleinanzeigen.de/s-wohnung-mieten/darmstadt/wohnung/k0c203l4888"
                ],
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
        # Telegram настройки (обязательные)
        if os.getenv('TELEGRAM_BOT_TOKEN'):
            self.config['telegram']['bot_token'] = os.getenv('TELEGRAM_BOT_TOKEN')
        if os.getenv('TELEGRAM_CHAT_ID'):
            self.config['telegram']['chat_id'] = os.getenv('TELEGRAM_CHAT_ID')
            
        # Search URLs (опционально)
        if os.getenv('SEARCH_URLS'):
            self.config['search_urls'] = os.getenv('SEARCH_URLS').split(';')
            
        # Настройки парсера (опционально)
        if os.getenv('CHECK_INTERVAL_MINUTES'):
            self.config.setdefault('settings', {})['check_interval_minutes'] = int(os.getenv('CHECK_INTERVAL_MINUTES'))
        if os.getenv('MAX_RETRIES'):
            self.config.setdefault('settings', {})['max_retries'] = int(os.getenv('MAX_RETRIES'))
        if os.getenv('RANDOM_DELAY_MIN'):
            self.config.setdefault('settings', {})['random_delay_min'] = int(os.getenv('RANDOM_DELAY_MIN'))
        if os.getenv('RANDOM_DELAY_MAX'):
            self.config.setdefault('settings', {})['random_delay_max'] = int(os.getenv('RANDOM_DELAY_MAX'))
            
        # Фильтры (опционально)
        if os.getenv('MIN_PRICE'):
            self.config.setdefault('filters', {})['min_price'] = int(os.getenv('MIN_PRICE'))
        if os.getenv('MAX_PRICE'):
            self.config.setdefault('filters', {})['max_price'] = int(os.getenv('MAX_PRICE'))
        if os.getenv('EXCLUDE_TITLES'):
            self.config.setdefault('filters', {})['exclude_titles'] = os.getenv('EXCLUDE_TITLES').split(',')
            
        # Пути к файлам (опционально)  
        if os.getenv('DATABASE_PATH'):
            self.database_path = os.getenv('DATABASE_PATH')
        else:
            self.database_path = '/app/data/listings.db'
            
        if os.getenv('LOG_PATH'):
            self.log_path = os.getenv('LOG_PATH')
        else:
            self.log_path = '/app/logs/kleinanzeigen_parser.log'
    
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
        
        # Добавляем колонку date_posted если её нет (для обратной совместимости)
        try:
            self.cursor.execute('ALTER TABLE listings ADD COLUMN date_posted TEXT')
            self.conn.commit()
        except sqlite3.OperationalError:
            # Колонка уже существует
            pass
        self.conn.commit()
    
    def get_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        """Получение и парсинг HTML страницы"""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=10)
                
                # Проверка на специальные коды ошибок
                if response.status_code == 403:
                    self.send_status_notification("BLOCKED", f"HTTP 403 Forbidden для {url}")
                elif response.status_code == 429:
                    self.send_status_notification("BLOCKED", f"HTTP 429 Too Many Requests для {url}")
                elif response.status_code >= 500:
                    self.send_error_notification(f"Ошибка сервера {response.status_code} для {url}", "ОШИБКА СЕРВЕРА")
                
                response.raise_for_status()
                
                # Проверка кодировки
                if response.encoding != 'utf-8':
                    response.encoding = 'utf-8'
                
                # Проверка на блокировку по содержимому
                if self.check_for_blocking(response.text, url):
                    return None
                
                # Проверка на минимальный размер ответа
                if len(response.text) < 1000:
                    self.logger.warning(f"Подозрительно короткий ответ ({len(response.text)} символов) для {url}")
                    if attempt == retries - 1:
                        self.send_error_notification(f"Получен слишком короткий ответ от {url}", "ПОДОЗРИТЕЛЬНЫЙ ОТВЕТ")
                
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
                    
            except requests.exceptions.RequestException as e:
                error_msg = f"Ошибка при загрузке {url}: {e} (попытка {attempt + 1})"
                self.logger.warning(error_msg)
                if attempt == retries - 1:
                    self.send_error_notification(error_msg, "ОШИБКА ЗАПРОСА")
                    
            except Exception as e:
                error_msg = f"Неожиданная ошибка при загрузке {url}: {e}"
                self.logger.error(error_msg)
                if attempt == retries - 1:
                    self.send_error_notification(error_msg, "КРИТИЧЕСКАЯ ОШИБКА")
                
            if attempt < retries - 1:
                sleep_time = 2 ** attempt
                self.logger.info(f"Ожидание {sleep_time} сек. перед повторной попыткой...")
                time.sleep(sleep_time)
        
        return None
    
    def extract_listing_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Извлечение ссылок на объявления из списка"""
        links = []
        
        # Поиск ссылок на объявления в разных форматах
        selectors = [
            'article h2 a',  # Основной селектор для заголовков объявлений
            'a[href*="/s-anzeige/"]',  # Любые ссылки на объявления
            '.aditem-main a'  # Альтернативный селектор
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                href = element.get('href')
                if href and '/s-anzeige/' in href:
                    full_url = urljoin(base_url, href)
                    if full_url not in links:
                        links.append(full_url)
        
        self.logger.info(f"Найдено {len(links)} ссылок на объявления")
        return links
    
    def extract_listing_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Извлечение даты публикации объявления"""
        try:
            # Различные селекторы для даты
            date_selectors = [
                '#viewad-extra-info',
                '.aditem-main--top--right', 
                '.aditem-addon',
                '.aditem-details--top--right'
            ]
            
            date_patterns = [
                r'(\d{1,2}\.\d{1,2}\.\d{4})',  # DD.MM.YYYY
                r'(Heute)',                    # Heute
                r'(Gestern)',                  # Gestern  
                r'(\d{1,2}\.\d{1,2}\.\d{2})', # DD.MM.YY
            ]
            
            page_text = soup.get_text()
            
            # Ищем текущую дату
            today = datetime.now()
            
            # Проверяем на "Heute" (сегодня)
            if 'heute' in page_text.lower():
                return today
            
            # Проверяем на "Gestern" (вчера)  
            if 'gestern' in page_text.lower():
                return today - timedelta(days=1)
            
            # Ищем конкретную дату
            for selector in date_selectors:
                date_elem = soup.select_one(selector)
                if date_elem:
                    date_text = date_elem.get_text()
                    
                    for pattern in date_patterns:
                        match = re.search(pattern, date_text)
                        if match:
                            date_str = match.group(1)
                            
                            if date_str == 'Heute':
                                return today
                            elif date_str == 'Gestern':
                                return today - timedelta(days=1)
                            else:
                                # Парсим дату
                                try:
                                    if len(date_str.split('.')) == 3:
                                        day, month, year = date_str.split('.')
                                        if len(year) == 2:
                                            year = '20' + year
                                        return datetime(int(year), int(month), int(day))
                                except ValueError:
                                    continue
            
            # Если дата не найдена, ищем в общем тексте страницы
            for pattern in date_patterns:
                matches = re.findall(pattern, page_text)
                if matches:
                    for match in matches:
                        if match == 'Heute':
                            return today
                        elif match == 'Gestern':
                            return today - timedelta(days=1)
                        else:
                            try:
                                if '.' in match and len(match.split('.')) == 3:
                                    day, month, year = match.split('.')
                                    if len(year) == 2:
                                        year = '20' + year
                                    parsed_date = datetime(int(year), int(month), int(day))
                                    # Возвращаем только если дата разумная (не старше 30 дней)
                                    if (today - parsed_date).days <= 30:
                                        return parsed_date
                            except ValueError:
                                continue
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Ошибка при извлечении даты: {e}")
            return None
    
    def is_listing_from_today(self, listing_date: Optional[datetime]) -> bool:
        """Проверка, что объявление опубликовано недавно"""
        if not listing_date:
            # Если дату не удалось определить, считаем что объявление свежее
            # (лучше не пропустить новое объявление)
            return True
        
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

    def extract_listing_data(self, soup: BeautifulSoup, url: str) -> Optional[Dict]:
        """Извлечение данных из отдельного объявления"""
        try:
            # Извлечение заголовка
            title_elem = soup.find('h1')
            title = title_elem.get_text(strip=True) if title_elem else "Без названия"
            
            # Извлечение цены
            price = None
            price_selectors = [
                '.boxedarticle--price',
                '.aditem-main--middle--price-shipping--price',
                'h2:contains("€")',
                '.price-label'
            ]
            
            for selector in price_selectors:
                if ':contains(' in selector:
                    price_elem = soup.find('h2', string=re.compile(r'€'))
                else:
                    price_elem = soup.select_one(selector)
                
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    price_match = re.search(r'(\d+(?:\.\d+)?)', price_text.replace('.', '').replace(',', ''))
                    if price_match:
                        price = int(float(price_match.group(1)))
                        break
            
            # Извлечение размера и количества комнат
            size = None
            rooms = None
            
            # Поиск информации о размере и комнатах в различных местах
            details_section = soup.find('dl') or soup.find('div', class_='addetailslist')
            if details_section:
                text = details_section.get_text()
                
                # Размер квартиры
                size_match = re.search(r'(\d+)\s*m²', text)
                if size_match:
                    size = int(size_match.group(1))
                
                # Количество комнат
                rooms_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:Zi|Zimmer)', text)
                if rooms_match:
                    rooms = rooms_match.group(1).replace(',', '.')
            
            # Альтернативный поиск в тексте страницы
            if not size or not rooms:
                page_text = soup.get_text()
                if not size:
                    size_match = re.search(r'(\d+)\s*m²', page_text)
                    if size_match:
                        size = int(size_match.group(1))
                
                if not rooms:
                    rooms_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:Zi|Zimmer)', page_text)
                    if rooms_match:
                        rooms = rooms_match.group(1).replace(',', '.')
            
            # Извлечение локации
            location = None
            location_selectors = [
                '#viewad-locality',
                '.addetailslist--detail:contains("Ort")',
                '.aditem-main--top--left'
            ]
            
            for selector in location_selectors:
                if ':contains(' in selector:
                    location_elem = soup.find(class_='addetailslist--detail', string=re.compile(r'Ort|PLZ'))
                else:
                    location_elem = soup.select_one(selector)
                
                if location_elem:
                    location = location_elem.get_text(strip=True)
                    break
            
            # Если не нашли в специальных селекторах, ищем в тексте
            if not location:
                location_match = re.search(r'\d{5}\s+[A-Za-zÄÖÜäöüß\s-]+', soup.get_text())
                if location_match:
                    location = location_match.group().strip()
            
            # Извлечение описания
            description_elem = soup.find('p', {'id': 'viewad-description-text'}) or \
                             soup.find('div', class_='addetailslist--description') or \
                             soup.find('div', class_='adview--description')
            
            description = description_elem.get_text(strip=True) if description_elem else ""
            
            # Извлечение даты публикации
            listing_date = self.extract_listing_date(soup)
            
            # Проверяем, что объявление опубликовано сегодня
            if not self.is_listing_from_today(listing_date):
                date_str = listing_date.strftime('%d.%m.%Y') if listing_date else "неизвестна"
                self.logger.info(f"Объявление пропущено - дата публикации: {date_str} (не сегодня): {title}")
                return None
            
            # Извлечение ID объявления из URL
            listing_id = re.search(r'/(\d+)-', url)
            listing_id = listing_id.group(1) if listing_id else hashlib.md5(url.encode()).hexdigest()[:10]
            
            # Создание хэша для проверки уникальности
            hash_string = f"{title}_{price}_{size}_{location}"
            listing_hash = hashlib.md5(hash_string.encode('utf-8')).hexdigest()
            
            listing_data = {
                'id': listing_id,
                'title': title,
                'price': price,
                'size': size,
                'rooms': rooms,
                'location': location,
                'description': description[:500] if description else "",  # Ограничиваем длину
                'url': url,
                'date_posted': listing_date.isoformat() if listing_date else None,
                'date_found': datetime.now().isoformat(),
                'hash': listing_hash
            }
            
            date_str = listing_date.strftime('%d.%m.%Y') if listing_date else "сегодня"
            self.logger.info(f"Извлечены данные: {title} - {price}€ - {location} - дата: {date_str}")
            return listing_data
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении данных из {url}: {e}")
            return None
    
    def check_filters(self, listing: Dict) -> bool:
        """Проверка соответствия объявления фильтрам"""
        filters = self.config.get('filters', {})
        
        # Проверка максимальной цены
        if filters.get('max_price') and listing.get('price'):
            if listing['price'] > filters['max_price']:
                return False
        
        # Проверка минимального размера
        if filters.get('min_size') and listing.get('size'):
            if listing['size'] < filters['min_size']:
                return False
        
        # Проверка максимального размера
        if filters.get('max_size') and listing.get('size'):
            if listing['size'] > filters['max_size']:
                return False
        
        # Проверка исключаемых слов
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
            self.cursor.execute('''
                INSERT OR REPLACE INTO listings 
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
            # Объявление уже существует
            return False
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении объявления: {e}")
            return False
    
    def send_telegram_notification(self, listing: Dict):
        """Отправка уведомления в Telegram"""
        if not self.bot or not self.config.get('telegram', {}).get('chat_id'):
            self.logger.warning("Telegram bot не настроен")
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
            
            self.bot.send_message(
                chat_id=self.config['telegram']['chat_id'],
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=False
            )
            
            # Отмечаем как отправленное
            self.cursor.execute(
                'UPDATE listings SET notified = TRUE WHERE id = ?',
                (listing['id'],)
            )
            self.conn.commit()
            
            self.logger.info(f"Уведомление отправлено для: {listing['title']}")
            
        except Exception as e:
            self.logger.error(f"Ошибка при отправке уведомления: {e}")
            self.send_error_notification(f"Ошибка при отправке уведомления о квартире: {e}")
    
    def send_error_notification(self, error_message: str, error_type: str = "ОШИБКА"):
        """Отправка уведомления об ошибке в Telegram"""
        if not self.bot or not self.config.get('telegram', {}).get('chat_id'):
            return
        
        try:
            message = f"🚨 *{error_type} ПАРСЕРА*\n\n"
            message += f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            message += f"📝 Описание: `{error_message}`\n"
            message += f"🔢 Попыток подряд: {self.consecutive_failures}\n"
            
            if self.last_successful_run:
                time_since = datetime.now() - datetime.fromisoformat(self.last_successful_run)
                hours = int(time_since.total_seconds() / 3600)
                message += f"⏳ Последний успешный запуск: {hours}ч назад\n"
            
            self.bot.send_message(
                chat_id=self.config['telegram']['chat_id'],
                text=message,
                parse_mode='Markdown'
            )
            
            self.logger.info(f"Отправлено уведомление об ошибке: {error_message}")
            
        except Exception as e:
            self.logger.error(f"Не удалось отправить уведомление об ошибке: {e}")
    
    def send_status_notification(self, status_type: str, details: str = ""):
        """Отправка уведомлений о статусе парсера"""
        if not self.bot or not self.config.get('telegram', {}).get('chat_id'):
            return
        
        try:
            if status_type == "NO_RESULTS":
                message = f"🔍 *МОНИТОРИНГ ПАРСЕРА*\n\n"
                message += f"⚠️ Уже 30 минут не найдено новых объявлений\n"
                message += f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                message += f"🔢 Всего запусков: {self.total_runs}\n"
                message += f"📊 Последних объявлений: {self.last_listings_found}\n"
                message += f"\n💡 Возможные причины:\n"
                message += f"• Нет новых объявлений\n"
                message += f"• Изменилась структура сайта\n"
                message += f"• Проблемы с доступом к сайту"
                
            elif status_type == "BLOCKED":
                message = f"🚫 *САЙТ ЗАБЛОКИРОВАЛ ПАРСЕР*\n\n"
                message += f"⚠️ Возможная блокировка доступа\n"
                message += f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                message += f"📝 Детали: {details}\n"
                message += f"\n💡 Рекомендации:\n"
                message += f"• Увеличить задержку между запросами\n"
                message += f"• Изменить User-Agent\n"
                message += f"• Проверить доступность сайта"
                
            elif status_type == "RECOVERY":
                message = f"✅ *ПАРСЕР ВОССТАНОВЛЕН*\n\n"
                message += f"🎉 Работа парсера возобновлена!\n"
                message += f"⏰ Время восстановления: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                message += f"📊 Найдено объявлений: {details}\n"
                
            else:
                message = f"📊 *СТАТУС ПАРСЕРА*\n\n{details}"
            
            self.bot.send_message(
                chat_id=self.config['telegram']['chat_id'],
                text=message,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            self.logger.error(f"Ошибка при отправке статусного уведомления: {e}")
    
    def check_for_blocking(self, response_text: str, url: str) -> bool:
        """Проверка на блокировку сайтом"""
        blocking_indicators = [
            "access denied",
            "blocked",
            "captcha",
            "robot",
            "bot detection",
            "rate limit",
            "too many requests",
            "403 forbidden",
            "cloudflare"
        ]
        
        text_lower = response_text.lower()
        for indicator in blocking_indicators:
            if indicator in text_lower:
                self.logger.warning(f"Обнаружен индикатор блокировки: {indicator}")
                self.send_status_notification("BLOCKED", f"Индикатор: {indicator}, URL: {url}")
                return True
                
        return False
    
    def parse_listings(self):
        """Основной метод парсинга"""
        start_time = datetime.now()
        self.total_runs += 1
        
        self.logger.info(f"Начинаем парсинг объявлений (запуск #{self.total_runs})")
        
        new_listings_count = 0
        total_processed = 0
        errors_count = 0
        
        try:
            for search_url in self.config.get('search_urls', []):
                self.logger.info(f"Парсинг страницы: {search_url}")
                
                # Получаем страницу со списком
                soup = self.get_page(search_url)
                if not soup:
                    errors_count += 1
                    self.send_error_notification(f"Не удалось получить список объявлений с {search_url}")
                    continue
                
                # Извлекаем ссылки на объявления
                listing_links = self.extract_listing_links(soup, search_url)
                
                if not listing_links:
                    self.logger.warning(f"Не найдено ссылок на объявления на странице {search_url}")
                    self.send_error_notification(f"Не найдено объявлений на {search_url}. Возможно изменилась структура сайта.", "ПРЕДУПРЕЖДЕНИЕ")
                    continue
                
                max_listings = self.config.get('settings', {}).get('max_listings_per_run', 50)
                request_delay = self.config.get('settings', {}).get('request_delay', 2)
                
                for i, link in enumerate(listing_links[:max_listings]):
                    total_processed += 1
                    self.logger.info(f"Обрабатываем объявление {i+1}/{min(len(listing_links), max_listings)}: {link}")
                    
                    try:
                        # Получаем страницу объявления
                        listing_soup = self.get_page(link)
                        if not listing_soup:
                            errors_count += 1
                            continue
                        
                        # Извлекаем данные
                        listing_data = self.extract_listing_data(listing_soup, link)
                        if not listing_data:
                            errors_count += 1
                            continue
                        
                        # Проверяем фильтры
                        if not self.check_filters(listing_data):
                            self.logger.info(f"Объявление не прошло фильтры: {listing_data['title']}")
                            continue
                        
                        # Сохраняем в базу
                        is_new = self.save_listing(listing_data)
                        if is_new:
                            new_listings_count += 1
                            self.logger.info(f"Новое объявление: {listing_data['title']}")
                            
                            # Отправляем уведомление
                            self.send_telegram_notification(listing_data)
                        
                    except Exception as e:
                        errors_count += 1
                        self.logger.error(f"Ошибка при обработке объявления {link}: {e}")
                        if errors_count > 5:  # Если слишком много ошибок
                            self.send_error_notification(f"Множественные ошибки при парсинге. Последняя: {e}", "КРИТИЧЕСКАЯ ОШИБКА")
                    
                    # Случайная задержка между запросами
                    settings = self.config.get('settings', {})
                    if settings.get('random_delay', False):
                        import random
                        min_delay = settings.get('min_delay', 3)
                        max_delay = settings.get('max_delay', 8)
                        delay = random.uniform(min_delay, max_delay)
                    else:
                        delay = request_delay
                    
                    self.logger.info(f"Ожидание {delay:.1f} сек...")
                    time.sleep(delay)
            
            # Обновляем статистику
            duration = datetime.now() - start_time
            self.last_listings_found = new_listings_count
            
            if new_listings_count > 0:
                # Успешный запуск с результатами
                self.last_successful_run = datetime.now().isoformat()
                self.consecutive_failures = 0
                
                if self.consecutive_failures >= 3:  # Восстановление после сбоев
                    self.send_status_notification("RECOVERY", str(new_listings_count))
            else:
                # Запуск без результатов
                self.consecutive_failures += 1
                
                # Уведомления о длительном отсутствии результатов
                if self.consecutive_failures == 2:  # После 1 часа без результатов
                    self.send_status_notification("NO_RESULTS")
                elif self.consecutive_failures >= 6:  # Каждые 3 часа после этого
                    if self.consecutive_failures % 6 == 0:
                        self.send_status_notification("NO_RESULTS")
            
            # Если слишком много ошибок
            if errors_count > total_processed * 0.5:  # Больше 50% ошибок
                self.send_error_notification(f"Высокий процент ошибок: {errors_count}/{total_processed}", "КРИТИЧЕСКАЯ ОШИБКА")
            
            self.logger.info(f"Парсинг завершен за {duration.total_seconds():.1f}сек. "
                           f"Новых объявлений: {new_listings_count}, "
                           f"Обработано: {total_processed}, "
                           f"Ошибок: {errors_count}")
                           
        except Exception as e:
            # Критическая ошибка всего парсинга
            self.consecutive_failures += 1
            error_details = f"{str(e)}\n\nТрассировка:\n{traceback.format_exc()}"
            self.logger.error(f"Критическая ошибка парсинга: {error_details}")
            self.send_error_notification(f"Критическая ошибка: {e}", "КРИТИЧЕСКАЯ ОШИБКА")
    
    def send_daily_report(self):
        """Отправка ежедневного отчета"""
        try:
            # Статистика за последние 24 часа
            yesterday = (datetime.now() - timedelta(days=1)).isoformat()
            
            self.cursor.execute("""
                SELECT COUNT(*) FROM listings 
                WHERE date_found >= ?
            """, (yesterday,))
            listings_24h = self.cursor.fetchone()[0]
            
            self.cursor.execute("""
                SELECT COUNT(*) FROM listings 
                WHERE date_found >= ? AND notified = 1
            """, (yesterday,))
            notified_24h = self.cursor.fetchone()[0]
            
            # Общая статистика
            self.cursor.execute("SELECT COUNT(*) FROM listings")
            total_listings = self.cursor.fetchone()[0]
            
            message = f"📊 *ЕЖЕДНЕВНЫЙ ОТЧЕТ ПАРСЕРА*\n\n"
            message += f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n"
            message += f"🆕 Найдено за 24ч: {listings_24h} объявлений\n"
            message += f"📨 Отправлено уведомлений: {notified_24h}\n"
            message += f"📊 Всего в базе: {total_listings} объявлений\n"
            message += f"🔢 Всего запусков: {self.total_runs}\n"
            message += f"❌ Сбоев подряд: {self.consecutive_failures}\n"
            
            if self.last_successful_run:
                last_success = datetime.fromisoformat(self.last_successful_run)
                time_since = datetime.now() - last_success
                hours = int(time_since.total_seconds() / 3600)
                message += f"✅ Последний успех: {hours}ч назад\n"
            
            message += f"\n🤖 Парсер работает нормально!"
            
            self.send_status_notification("DAILY_REPORT", message)
            
        except Exception as e:
            self.logger.error(f"Ошибка при генерации ежедневного отчета: {e}")

    def run_continuous(self):
        """Запуск парсера в непрерывном режиме"""
        interval = self.config.get('update_interval', 30)
        self.logger.info(f"Запуск парсера с интервалом {interval} минут")
        
        # Отправляем уведомление о запуске
        try:
            startup_message = f"🚀 *ПАРСЕР ЗАПУЩЕН*\n\n"
            startup_message += f"⏰ Время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            startup_message += f"🔄 Интервал: {interval} минут\n"
            startup_message += f"🔍 URL поиска: {len(self.config.get('search_urls', []))} шт.\n"
            startup_message += f"\n✅ Мониторинг активен!"
            
            if self.bot and self.config.get('telegram', {}).get('chat_id'):
                self.bot.send_message(
                    chat_id=self.config['telegram']['chat_id'],
                    text=startup_message,
                    parse_mode='Markdown'
                )
        except Exception as e:
            self.logger.error(f"Ошибка при отправке уведомления о запуске: {e}")
        
        # Планируем задачи
        schedule.every(interval).minutes.do(self.parse_listings)
        schedule.every().day.at("09:00").do(self.send_daily_report)  # Ежедневный отчет в 9 утра
        
        # Выполняем первый раз сразу
        self.parse_listings()
        
        # Основной цикл
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Проверяем каждую минуту
        except KeyboardInterrupt:
            self.logger.info("Получен сигнал остановки")
            try:
                shutdown_message = f"🛑 *ПАРСЕР ОСТАНОВЛЕН*\n\n"
                shutdown_message += f"⏰ Время остановки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                shutdown_message += f"🔢 Всего было запусков: {self.total_runs}\n"
                
                if self.bot and self.config.get('telegram', {}).get('chat_id'):
                    self.bot.send_message(
                        chat_id=self.config['telegram']['chat_id'],
                        text=shutdown_message,
                        parse_mode='Markdown'
                    )
            except:
                pass
            raise
    
    def __del__(self):
        """Деструктор для закрытия соединения с БД"""
        if hasattr(self, 'conn'):
            self.conn.close()


def main():
    """Главная функция"""
    parser = KleinanzeigenParser()
    
    try:
        # Запуск парсера в непрерывном режиме
        parser.run_continuous()
    except KeyboardInterrupt:
        print("\nПарсер остановлен пользователем")
    except Exception as e:
        parser.logger.error(f"Критическая ошибка: {e}")


if __name__ == "__main__":
    main()