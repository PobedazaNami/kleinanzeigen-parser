#!/usr/bin/env python3
"""
ImmobilienScout24 Parser для квартир в аренду
Парсит объявления с ImmobilienScout24.de и отправляет уведомления в Telegram
Использует Firecrawl API для обхода защиты от ботов
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import logging
import re
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin
import hashlib

from base_parser import BaseParser

# Попытка импортировать Firecrawl
try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False


class ImmobilienScout24Parser(BaseParser):
    """Класс для парсинга объявлений с ImmobilienScout24.de с использованием Firecrawl API"""
    
    def __init__(self, config_file: str = "config.json"):
        """Инициализация парсера для ImmobilienScout24"""
        super().__init__(config_file, parser_name="immobilienscout24")
        
        # Инициализация Firecrawl
        self.firecrawl_api_key = os.getenv('FIRECRAWL_API_KEY')
        self.use_firecrawl = self.config.get('immobilienscout24_settings', {}).get('use_firecrawl', True)
        
        if self.use_firecrawl and self.firecrawl_api_key and FIRECRAWL_AVAILABLE:
            try:
                self.firecrawl = FirecrawlApp(api_key=self.firecrawl_api_key)
                self.logger.info("✅ Firecrawl API инициализирован для ImmobilienScout24")
            except Exception as e:
                self.logger.error(f"❌ Ошибка инициализации Firecrawl: {e}")
                self.firecrawl = None
                self.use_firecrawl = False
        else:
            self.firecrawl = None
            if self.use_firecrawl and not self.firecrawl_api_key:
                self.logger.warning("⚠️  FIRECRAWL_API_KEY не установлен в ENV")
                self.use_firecrawl = False
        
        # Создаем новую session для ImmobilienScout24
        self.session = requests.Session()
        
        # Headers для имитации браузера
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
        })
        
        self.logger.info(f"Инициализирован парсер для ImmobilienScout24.de (Firecrawl: {'✅' if self.use_firecrawl else '❌'})")
    
    def get_page_with_firecrawl(self, url: str) -> Optional[BeautifulSoup]:
        """Получение страницы через Firecrawl API"""
        if not self.use_firecrawl or not self.firecrawl:
            return None
        
        try:
            self.logger.info(f"🔥 Запрос через Firecrawl: {url}")
            
            # Используем scrape метод Firecrawl (правильное API v2)
            result = self.firecrawl.scrape(
                url,
                formats=['html'],
                only_main_content=False,
                wait_for=3000  # Ждем 3 секунды для загрузки JavaScript
            )
            
            if result and hasattr(result, 'html') and result.html:
                html_content = result.html
                self.logger.info(f"✅ Получено через Firecrawl: {len(html_content)} символов")
                return BeautifulSoup(html_content, 'html.parser')
            elif result and hasattr(result, 'markdown') and result.markdown:
                html_content = result.markdown
                self.logger.info(f"✅ Получено через Firecrawl (markdown): {len(html_content)} символов")
                return BeautifulSoup(html_content, 'html.parser')
            else:
                self.logger.warning(f"⚠️  Firecrawl не вернул HTML для {url}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка Firecrawl для {url}: {e}")
            return None
    
    def get_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        """Переопределенный метод получения страницы с использованием Firecrawl"""
        
        # Для ImmobilienScout24 ВСЕГДА используем Firecrawl (возвращает 401)
        if self.use_firecrawl and 'immobilienscout24.de' in url:
            soup = self.get_page_with_firecrawl(url)
            if soup:
                return soup
            else:
                self.logger.error("⚠️  Firecrawl не сработал, ImmobilienScout24 блокирует запросы")
                return None
        
        # Fallback на обычный HTTP запрос (скорее всего не сработает)
        return super().get_page(url, retries)
    
    def extract_listing_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Извлечение ссылок на объявления из списка ImmobilienScout24 (только с меткой Neu)"""
        links = []
        
        # Ищем все элементы со значком "Neu"
        # На ImmobilienScout24 могут быть разные варианты
        neu_elements = []
        
        # Вариант 1: data-testid
        neu_elements.extend(soup.find_all(attrs={'data-testid': lambda x: x and 'new' in x.lower()}))
        
        # Вариант 2: текст "Neu"
        neu_elements.extend(soup.find_all(string=lambda text: text and text.strip() == 'Neu'))
        
        # Вариант 3: class содержит "new"
        neu_elements.extend(soup.find_all(class_=lambda x: x and 'new' in str(x).lower()))
        
        self.logger.info(f"Найдено {len(neu_elements)} элементов с меткой 'Neu' на странице")
        
        # Для каждого значка "Neu" ищем ближайшую ссылку на объявление
        for neu_element in neu_elements:
            # Поднимаемся вверх по дереву до контейнера карточки
            container = neu_element if hasattr(neu_element, 'parent') else neu_element.parent
            for _ in range(20):  # Максимум 20 уровней вверх
                if container is None:
                    break
                container = container.parent
                
                # Ищем ссылку с /expose/ в этом контейнере
                if container:
                    link = container.find('a', href=lambda href: href and '/expose/' in href)
                    if link:
                        href = link.get('href')
                        # Формируем полный URL
                        if href.startswith('http'):
                            full_url = href
                        elif href.startswith('/'):
                            full_url = 'https://www.immobilienscout24.de' + href
                        else:
                            full_url = urljoin(base_url, href)
                        
                        # Добавляем только уникальные ссылки
                        if full_url not in links:
                            links.append(full_url)
                            self.logger.debug(f"Найдено новое объявление: {full_url}")
                        break
        
        self.logger.info(f"Найдено {len(links)} НОВЫХ объявлений с меткой 'Neu' на ImmobilienScout24")
        return links
    
    def extract_listing_data(self, soup: BeautifulSoup, url: str) -> Optional[Dict]:
        """Извлечение данных из отдельного объявления ImmobilienScout24"""
        try:
            # Извлечение заголовка
            title_selectors = [
                'h1[id="expose-title"]',
                'h1.font-nowrap',
                'h1',
            ]
            
            title = "Без названия"
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break
            
            # Извлечение цены (немецкий формат)
            price = None
            price_selectors = [
                'dd[class*="price"]',
                'div[class*="price"]',
                'span[class*="price"]',
            ]
            
            for selector in price_selectors:
                price_elem = soup.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    price_text = re.sub(r'[^\d,.]', '', price_text)
                    
                    # Немецкий формат: 753.71 € = 753 евро
                    if ',' in price_text:
                        price_text = price_text.replace('.', '').replace(',', '.')
                    elif '.' in price_text:
                        parts = price_text.split('.')
                        if len(parts) == 2 and len(parts[1]) == 2:
                            price_text = price_text
                        else:
                            price_text = price_text.replace('.', '')
                    
                    try:
                        price = int(float(price_text))
                        break
                    except ValueError:
                        continue
            
            # Извлечение размера и количества комнат
            size = None
            rooms = None
            
            # Ищем в критериях
            criteria = soup.find_all(['dd', 'div', 'span'], class_=lambda x: x and any(keyword in str(x).lower() for keyword in ['criteria', 'data', 'detail']))
            
            for elem in criteria:
                elem_text = elem.get_text()
                
                # Размер квартиры
                if not size and 'm²' in elem_text:
                    size_match = re.search(r'(\d+(?:[.,]\d+)?)\s*m²', elem_text)
                    if size_match:
                        size_str = size_match.group(1).replace(',', '.')
                        size = int(float(size_str))
                
                # Количество комнат
                if not rooms and 'zimmer' in elem_text.lower():
                    rooms_match = re.search(r'(\d+(?:[.,]\d+)?)', elem_text)
                    if rooms_match:
                        rooms = rooms_match.group(1).replace(',', '.')
            
            # Извлечение локации
            location = None
            location_selectors = [
                'span[class*="address"]',
                'div[class*="address"]',
                'dd[class*="address"]',
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
                'pre[class*="description"]',
                'div[class*="description"]',
                'p[class*="description"]',
            ]
            
            description = ""
            for selector in description_selectors:
                description_elem = soup.select_one(selector)
                if description_elem:
                    description = description_elem.get_text(strip=True)
                    break
            
            # Для ImmobilienScout24 дата не нужна - мы фильтруем по значку "Neu"
            listing_date = datetime.now()
            self.logger.debug("Для ImmobilienScout24 используем текущую дату (фильтр по значку Neu)")
            
            # Извлечение ID объявления из URL
            listing_id_match = re.search(r'/expose/(\d+)', url)
            if listing_id_match:
                listing_id = 'immoscout_' + listing_id_match.group(1)
            else:
                listing_id = 'immoscout_' + hashlib.md5(url.encode()).hexdigest()[:10]
            
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
                'parser_source': 'immobilienscout24'
            }
            
            self.logger.info(f"✅ Извлечены данные ImmobilienScout24 (NEW): {title} - {price}€ - {location}")
            return listing_data
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении данных из ImmobilienScout24 {url}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None

    def parse_listings(self):
        """Основной метод парсинга с ограничением для ImmobilienScout24"""
        # Устанавливаем лимит 2 объявления для ImmobilienScout24
        original_max = self.config.get('settings', {}).get('max_listings_per_run', 50)
        scout_max = self.config.get('settings', {}).get('max_listings_immobilienscout24', 2)
        
        # Устанавливаем лимит для ImmobilienScout24
        self.config['settings']['max_listings_per_run'] = scout_max
        self.logger.info(f"Ограничение для ImmobilienScout24: максимум {scout_max} объявлений")
        
        try:
            # Вызываем родительский метод
            result = super().parse_listings()
            return result
        finally:
            # Восстанавливаем оригинальное значение
            self.config['settings']['max_listings_per_run'] = original_max


if __name__ == "__main__":
    # Тестовый запуск
    parser = ImmobilienScout24Parser()
    parser.parse_listings()
