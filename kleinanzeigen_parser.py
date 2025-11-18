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

from base_parser import BaseParser


class KleinanzeigenParser(BaseParser):
    """Основной класс для парсинга объявлений с Kleinanzeigen"""
    
    def __init__(self, config_file: str = "config.json"):
        """Инициализация парсера с конфигурацией"""
        super().__init__(config_file, parser_name="kleinanzeigen")
        
        # Специфичные настройки для Kleinanzeigen
        self.session.headers.update({
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '"Google Chrome";v="120", "Chromium";v="120", "Not=A?Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"'
        })
        
        self.logger.info("Инициализирован парсер для Kleinanzeigen.de")
        
    def get_initial_cookies(self):
        """Получение начальных cookies с главной страницы Kleinanzeigen"""
        try:
            self.logger.info("Получение начальных cookies...")
            response = self.session.get('https://www.kleinanzeigen.de/', timeout=30)
            if response.status_code == 200:
                self.logger.info("Cookies получены успешно")
                return True
            else:
                self.logger.warning(f"Не удалось получить cookies: {response.status_code}")
                return False
        except Exception as e:
            self.logger.warning(f"Ошибка при получении cookies: {e}")
            return False
    
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
            today = datetime.now()
            
            # ПРИОРИТЕТ 1: Ищем точную дату в #viewad-extra-info (самый надежный источник)
            viewad_info = soup.select_one('#viewad-extra-info')
            if viewad_info:
                info_text = viewad_info.get_text()
                self.logger.debug(f"Текст из #viewad-extra-info: {info_text[:200]}")
                
                # Ищем дату в формате DD.MM.YYYY
                date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})', info_text)
                if date_match:
                    date_str = date_match.group(1)
                    try:
                        day, month, year = date_str.split('.')
                        parsed_date = datetime(int(year), int(month), int(day))
                        self.logger.debug(f"Найдена точная дата в #viewad-extra-info: {parsed_date.strftime('%d.%m.%Y')}")
                        return parsed_date
                    except ValueError:
                        pass
                
                # Если точной даты нет, проверяем на "Heute" или "Gestern"
                if 'heute' in info_text.lower():
                    self.logger.debug(f"Найден 'Heute' в #viewad-extra-info")
                    return today
                if 'gestern' in info_text.lower():
                    self.logger.debug(f"Найден 'Gestern' в #viewad-extra-info")
                    return today - timedelta(days=1)
            
            # ПРИОРИТЕТ 2: Ищем в других селекторах с более строгой проверкой
            date_selectors = [
                '.aditem-details--top--right',
                '.aditem-addon',  
                '.ad-keyfacts',
                '.aditem-main--top--right'
            ]
            
            for selector in date_selectors:
                date_elem = soup.select_one(selector)
                if date_elem:
                    date_text = date_elem.get_text()
                    self.logger.debug(f"Текст из {selector}: {date_text[:100]}")
                    
                    # Сначала ищем точную дату DD.MM.YYYY
                    date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})', date_text)
                    if date_match:
                        date_str = date_match.group(1)
                        try:
                            day, month, year = date_str.split('.')
                            parsed_date = datetime(int(year), int(month), int(day))
                            self.logger.debug(f"Найдена дата в {selector}: {parsed_date.strftime('%d.%m.%Y')}")
                            return parsed_date
                        except ValueError:
                            continue
                    
                    # Проверяем на "Heute" с временем (например "Heute, 22:20")
                    if re.search(r'heute\s*,?\s*\d{1,2}:\d{2}', date_text.lower()):
                        self.logger.debug(f"Найден 'Heute' с временем в {selector}")
                        return today
                    
                    # Проверяем на "Heute" в контексте даты публикации
                    if ('heute' in date_text.lower() and 
                        ('eingestellt' in date_text.lower() or 'online' in date_text.lower() or 'veröffentlicht' in date_text.lower())):
                        self.logger.debug(f"Найден 'Heute' в контексте публикации в {selector}")
                        return today
                    
                    # Проверяем на "Gestern" с временем
                    if re.search(r'gestern\s*,?\s*\d{1,2}:\d{2}', date_text.lower()):
                        self.logger.debug(f"Найден 'Gestern' с временем в {selector}")
                        return today - timedelta(days=1)
                        
                    # Проверяем на "Gestern" в контексте  
                    if ('gestern' in date_text.lower() and 
                        ('eingestellt' in date_text.lower() or 'online' in date_text.lower() or 'veröffentlicht' in date_text.lower())):
                        self.logger.debug(f"Найден 'Gestern' в контексте публикации в {selector}")
                        return today - timedelta(days=1)
            
            # ПРИОРИТЕТ 3: Последняя попытка - ищем разумные даты во всем тексте
            self.logger.debug("Ищем дату во всем тексте страницы как последняя попытка")
            page_text = soup.get_text()
            date_matches = re.findall(r'(\d{1,2}\.\d{1,2}\.\d{4})', page_text)
            
            valid_dates = []
            for date_str in date_matches:
                try:
                    day, month, year = date_str.split('.')
                    parsed_date = datetime(int(year), int(month), int(day))
                    # Фильтруем только разумные даты (не в будущем и не старше 30 дней)
                    days_diff = (today - parsed_date).days
                    if -1 <= days_diff <= 30:  # Допускаем завтрашнюю дату
                        valid_dates.append((parsed_date, days_diff))
                except ValueError:
                    continue
            
            # Берем самую свежую дату (с минимальным days_diff)
            if valid_dates:
                valid_dates.sort(key=lambda x: x[1])  # Сортируем по days_diff
                best_date = valid_dates[0][0]
                self.logger.debug(f"Найдена лучшая дата в тексте: {best_date.strftime('%d.%m.%Y')}")
                return best_date
            
            self.logger.debug("Дата публикации не найдена")
            return None
            
        except Exception as e:
            self.logger.warning(f"Ошибка при извлечении даты: {e}")
            return None

    def extract_media_urls(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Извлечение URL изображений и видео из объявления"""
        media_urls = {
            'images': [],
            'videos': []
        }
        
        try:
            # Поиск изображений в галерее
            # Kleinanzeigen использует различные селекторы для изображений
            image_selectors = [
                'img[src*="img.kleinanzeigen.de"]',  # Основные изображения
                '.galleryimage img',  # Галерея изображений
                '#viewad-product img',  # Изображения в секции продукта
                '.imagegallery img',  # Альтернативная галерея
                'img.image',  # Общие изображения
            ]
            
            for selector in image_selectors:
                images = soup.select(selector)
                for img in images:
                    src = img.get('src') or img.get('data-src')
                    if src and 'http' in src:
                        # Получаем полноразмерное изображение (заменяем размер в URL)
                        # Kleinanzeigen обычно имеет размеры в URL типа $_59.JPG
                        full_size_url = re.sub(r'\$_\d+\.', '$.', src)
                        if full_size_url not in media_urls['images']:
                            media_urls['images'].append(full_size_url)
            
            # Поиск видео
            video_elements = soup.find_all('video')
            for video in video_elements:
                src = video.get('src')
                if src and 'http' in src:
                    media_urls['videos'].append(src)
                
                # Также проверяем source внутри video
                sources = video.find_all('source')
                for source in sources:
                    src = source.get('src')
                    if src and 'http' in src and src not in media_urls['videos']:
                        media_urls['videos'].append(src)
            
            self.logger.debug(f"Найдено изображений: {len(media_urls['images'])}, видео: {len(media_urls['videos'])}")
            
        except Exception as e:
            self.logger.warning(f"Ошибка при извлечении медиа: {e}")
        
        return media_urls

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
                # Ищем по структуре HTML (более надежно)
                for item in details_section.find_all(['dt', 'li']):
                    item_text = item.get_text().strip().lower()
                    
                    # Поиск размера
                    if 'wohnfläche' in item_text or 'wohnflache' in item_text:
                        value_elem = item.find('span', class_='addetailslist--detail--value')
                        if value_elem:
                            value_text = value_elem.get_text().strip()
                            size_match = re.search(r'(\d+)', value_text)
                            if size_match:
                                size = int(size_match.group(1))
                        elif item.name == 'dt':
                            dd_elem = item.find_next_sibling('dd')
                            if dd_elem:
                                value_text = dd_elem.get_text().strip()
                                size_match = re.search(r'(\d+)', value_text)
                                if size_match:
                                    size = int(size_match.group(1))
                    
                    # Поиск количества комнат
                    if 'zimmer' in item_text and 'schlafzimmer' not in item_text and 'badezimmer' not in item_text:
                        value_elem = item.find('span', class_='addetailslist--detail--value')
                        if value_elem:
                            value_text = value_elem.get_text().strip()
                            rooms_match = re.search(r'(\d+(?:[.,]\d+)?)', value_text)
                            if rooms_match:
                                rooms = rooms_match.group(1).replace(',', '.')
                        elif item.name == 'dt':
                            dd_elem = item.find_next_sibling('dd')
                            if dd_elem:
                                value_text = dd_elem.get_text().strip()
                                rooms_match = re.search(r'(\d+(?:[.,]\d+)?)', value_text)
                                if rooms_match:
                                    rooms = rooms_match.group(1).replace(',', '.')
                
                # Если не нашли по структуре, пробуем по тексту
                if not size or not rooms:
                    text = details_section.get_text()
                    
                    if not size:
                        size_match = re.search(r'(\d+)\s*m²', text)
                        if size_match:
                            size = int(size_match.group(1))
                    
                    if not rooms:
                        rooms_match = re.search(r'Zimmer\s+(\d+(?:[.,]\d+)?)', text, re.IGNORECASE)
                        if not rooms_match:
                            rooms_match = re.search(r'(\d+(?:[.,]\d+)?)\s+Zimmer', text, re.IGNORECASE)
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
                    rooms_match = re.search(r'Zimmer\s+(\d+(?:[.,]\d+)?)', page_text, re.IGNORECASE)
                    if not rooms_match:
                        rooms_match = re.search(r'(\d+(?:[.,]\d+)?)\s+Zimmer', page_text, re.IGNORECASE)
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
            
            # Извлечение медиа (изображения и видео)
            media_urls = self.extract_media_urls(soup)
            
            # Извлечение даты публикации
            listing_date = self.extract_listing_date(soup)
            
            # Проверяем, что объявление опубликовано недавно
            if not self.is_listing_from_today(listing_date):
                date_str = listing_date.strftime('%d.%m.%Y') if listing_date else "неизвестна"
                self.logger.info(f"Объявление пропущено - дата публикации: {date_str}: {title}")
                return "SKIPPED_BY_DATE"
            
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
                'description': description[:500] if description else "",
                'url': url,
                'date_posted': listing_date.isoformat() if listing_date else None,
                'date_found': datetime.now().isoformat(),
                'hash': listing_hash,
                'images': media_urls['images'],
                'videos': media_urls['videos']
            }
            
            date_str = listing_date.strftime('%d.%m.%Y') if listing_date else "сегодня"
            self.logger.info(f"Извлечены данные: {title} - {price}€ - {location} - дата: {date_str}")
            return listing_data
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении данных из {url}: {e}")
            return None
    
    def send_daily_report(self):
        """Отправка ежедневного отчета"""
        try:
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
        
        try:
            startup_message = f"🚀 *ПАРСЕР ЗАПУЩЕН*\n\n"
            startup_message += f"⏰ Время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            startup_message += f"🔄 Интервал: {interval} минут\n"
            startup_message += f"🔍 URL поиска: {len(self.config.get('search_urls', []))} шт.\n"
            startup_message += f"\n✅ Мониторинг активен!"
            
            self.send_telegram_sync(startup_message, parse_mode='Markdown')
        except Exception as e:
            self.logger.error(f"Ошибка при отправке уведомления о запуске: {e}")
        
        schedule.every(interval).minutes.do(self.parse_listings)
        schedule.every().day.at("09:00").do(self.send_daily_report)
        
        self.parse_listings()
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)
        except KeyboardInterrupt:
            self.logger.info("Получен сигнал остановки")
            try:
                shutdown_message = f"🛑 *ПАРСЕР ОСТАНОВЛЕН*\n\n"
                shutdown_message += f"⏰ Время остановки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                shutdown_message += f"🔢 Всего было запусков: {self.total_runs}\n"
                
                self.send_telegram_sync(shutdown_message, parse_mode='Markdown')
            except:
                pass
            raise


def main():
    """Главная функция"""
    parser = KleinanzeigenParser()
    
    try:
        parser.run_continuous()
    except KeyboardInterrupt:
        print("\nПарсер остановлен пользователем")
    except Exception as e:
        parser.logger.error(f"Критическая ошибка: {e}")


if __name__ == "__main__":
    main()
