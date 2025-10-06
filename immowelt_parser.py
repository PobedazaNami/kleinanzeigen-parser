#!/usr/bin/env python3
"""
Immowelt Parser для квартир в аренду
Парсит объявления с Immowelt.de и отправляет уведомления в Telegram
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import logging
import sqlite3
import re
import os
import asyncio
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
import requests as sync_requests

# Импортируем базовый класс
from kleinanzeigen_parser import KleinanzeigenParser


class ImmoweltParser(KleinanzeigenParser):
    """Класс для парсинга объявлений с Immowelt.de"""
    
    def __init__(self, config_file: str = "config.json"):
        """Инициализация парсера для Immowelt"""
        super().__init__(config_file)
        
        # Создаем отдельную session для Immowelt с более простыми headers
        self.session = requests.Session()
        
        # Более простые headers для Immowelt
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        })
        
        self.logger.info("Инициализирован парсер для Immowelt.de с отдельной session")
    
    def get_initial_cookies(self):
        """Получение начальных cookies с главной страницы Immowelt"""
        try:
            self.logger.info("Получение начальных cookies для Immowelt...")
            response = self.session.get('https://www.immowelt.de/', timeout=30)
            if response.status_code == 200:
                self.logger.info("Cookies для Immowelt получены успешно")
                return True
            else:
                self.logger.warning(f"Не удалось получить cookies для Immowelt: {response.status_code}")
                return False
        except Exception as e:
            self.logger.warning(f"Ошибка при получении cookies для Immowelt: {e}")
            return False
    
    def extract_listing_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Извлечение ссылок на объявления из списка Immowelt"""
        links = []
        
        # Ищем все ссылки с /expose/ в href
        all_links = soup.find_all('a', href=True)
        
        for element in all_links:
            href = element.get('href')
            if href and '/expose/' in href:
                # Immowelt использует полные URL
                if href.startswith('http'):
                    full_url = href
                elif href.startswith('/'):
                    full_url = 'https://www.immowelt.de' + href
                else:
                    full_url = urljoin(base_url, href)
                
                # Добавляем только уникальные ссылки
                if full_url not in links:
                    links.append(full_url)
        
        self.logger.info(f"Найдено {len(links)} ссылок на объявления Immowelt")
        return links
    
    def extract_listing_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Извлечение даты публикации объявления с Immowelt"""
        try:
            today = datetime.now()
            
            # Ищем дату в различных местах на странице Immowelt
            date_selectors = [
                'div[data-test="objectdata"] span',  # Основной селектор для даты
                '.hardfact',  # Жесткие факты
                'sd-cell-col',  # Дата в таблице
                '.objektdaten'  # Данные объекта
            ]
            
            for selector in date_selectors:
                date_elems = soup.select(selector)
                for date_elem in date_elems:
                    date_text = date_elem.get_text()
                    self.logger.debug(f"Проверяем текст: {date_text[:100]}")
                    
                    # Ищем точную дату DD.MM.YYYY
                    date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})', date_text)
                    if date_match:
                        date_str = date_match.group(1)
                        try:
                            day, month, year = date_str.split('.')
                            parsed_date = datetime(int(year), int(month), int(day))
                            self.logger.debug(f"Найдена дата: {parsed_date.strftime('%d.%m.%Y')}")
                            return parsed_date
                        except ValueError:
                            continue
                    
                    # Проверяем на относительные даты
                    lower_text = date_text.lower()
                    if any(word in lower_text for word in ['heute', 'today']):
                        self.logger.debug("Найден 'Heute'")
                        return today
                    
                    if any(word in lower_text for word in ['gestern', 'yesterday']):
                        self.logger.debug("Найден 'Gestern'")
                        return today - timedelta(days=1)
                    
                    # Проверяем на "vor X Tagen"
                    days_ago_match = re.search(r'vor\s+(\d+)\s+tag', lower_text)
                    if days_ago_match:
                        days_ago = int(days_ago_match.group(1))
                        parsed_date = today - timedelta(days=days_ago)
                        self.logger.debug(f"Найдено 'vor {days_ago} Tagen'")
                        return parsed_date
            
            # Если не нашли дату, возвращаем None
            self.logger.debug("Дата публикации не найдена на Immowelt")
            return None
            
        except Exception as e:
            self.logger.warning(f"Ошибка при извлечении даты из Immowelt: {e}")
            return None
    
    def extract_listing_data(self, soup: BeautifulSoup, url: str) -> Optional[Dict]:
        """Извлечение данных из отдельного объявления Immowelt"""
        try:
            # Извлечение заголовка
            title_selectors = [
                'h1[data-test="expose-title"]',
                'h1.ng-binding',
                'h1',
                '.expose_header h1'
            ]
            
            title = "Без названия"
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break
            
            # Извлечение цены
            price = None
            price_selectors = [
                'div[data-test="price"] strong',
                '.hardfact_value strong',
                'strong[data-test="kaltmiete"]',
                '.price_value'
            ]
            
            for selector in price_selectors:
                price_elem = soup.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    # Убираем все нецифровые символы кроме запятой и точки
                    price_text = re.sub(r'[^\d,.]', '', price_text)
                    price_match = re.search(r'(\d+(?:[.,]\d+)?)', price_text)
                    if price_match:
                        price_str = price_match.group(1).replace('.', '').replace(',', '.')
                        price = int(float(price_str))
                        break
            
            # Извлечение размера и количества комнат
            size = None
            rooms = None
            
            # Поиск в hardfacts (ключевые характеристики)
            hardfacts = soup.select('div[data-test="hardfact"]')
            for fact in hardfacts:
                fact_text = fact.get_text()
                
                # Размер квартиры
                if 'wohnfläche' in fact_text.lower() or 'm²' in fact_text.lower():
                    size_match = re.search(r'(\d+(?:[.,]\d+)?)\s*m²', fact_text)
                    if size_match:
                        size_str = size_match.group(1).replace(',', '.')
                        size = int(float(size_str))
                
                # Количество комнат
                if 'zimmer' in fact_text.lower():
                    rooms_match = re.search(r'(\d+(?:[.,]\d+)?)', fact_text)
                    if rooms_match:
                        rooms = rooms_match.group(1).replace(',', '.')
            
            # Альтернативный поиск в структурированных данных
            if not size or not rooms:
                # Ищем в sd-cell (structured data cells)
                cells = soup.select('sd-cell')
                for cell in cells:
                    cell_text = cell.get_text()
                    
                    if not size and ('wohnfläche' in cell_text.lower() or 'm²' in cell_text.lower()):
                        size_match = re.search(r'(\d+(?:[.,]\d+)?)\s*m²', cell_text)
                        if size_match:
                            size_str = size_match.group(1).replace(',', '.')
                            size = int(float(size_str))
                    
                    if not rooms and 'zimmer' in cell_text.lower():
                        rooms_match = re.search(r'(\d+(?:[.,]\d+)?)', cell_text)
                        if rooms_match:
                            rooms = rooms_match.group(1).replace(',', '.')
            
            # Извлечение локации
            location = None
            location_selectors = [
                'div[data-test="address"]',
                'span.location',
                '.expose_header .address',
                'p.address'
            ]
            
            for selector in location_selectors:
                location_elem = soup.select_one(selector)
                if location_elem:
                    location = location_elem.get_text(strip=True)
                    break
            
            # Если не нашли, ищем в тексте
            if not location:
                location_match = re.search(r'\d{5}\s+[A-Za-zÄÖÜäöüß\s-]+', soup.get_text())
                if location_match:
                    location = location_match.group().strip()
            
            # Извлечение описания
            description_selectors = [
                'div[data-test="description-text"]',
                'div.freitext',
                'pre#objectDescription',
                'div.beschreibung'
            ]
            
            description = ""
            for selector in description_selectors:
                description_elem = soup.select_one(selector)
                if description_elem:
                    description = description_elem.get_text(strip=True)
                    break
            
            # Извлечение даты публикации
            listing_date = self.extract_listing_date(soup)
            
            # Проверяем, что объявление опубликовано недавно
            if not self.is_listing_from_today(listing_date):
                date_str = listing_date.strftime('%d.%m.%Y') if listing_date else "неизвестна"
                self.logger.info(f"Объявление Immowelt пропущено - дата публикации: {date_str}: {title}")
                return "SKIPPED_BY_DATE"
            
            # Извлечение ID объявления из URL
            listing_id_match = re.search(r'/expose/(\d+)', url)
            if listing_id_match:
                listing_id = 'immowelt_' + listing_id_match.group(1)
            else:
                listing_id = 'immowelt_' + hashlib.md5(url.encode()).hexdigest()[:10]
            
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
            self.logger.info(f"Извлечены данные Immowelt: {title} - {price}€ - {location} - дата: {date_str}")
            return listing_data
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении данных из Immowelt {url}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None


if __name__ == "__main__":
    # Тестовый запуск
    parser = ImmoweltParser()
    parser.parse_listings()
