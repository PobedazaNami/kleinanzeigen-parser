#!/usr/bin/env python3
"""
Immowelt Parser для квартир в аренду
Парсит объявления с Immowelt.de и отправляет уведомления в Telegram
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


class ImmoweltParser(BaseParser):
    """Класс для парсинга объявлений с Immowelt.de с использованием Firecrawl API"""
    
    def __init__(self, config_file: str = "config.json"):
        """Инициализация парсера для Immowelt"""
        super().__init__(config_file, parser_name="immowelt")
        
        # Инициализация Firecrawl
        self.firecrawl_api_key = os.getenv('FIRECRAWL_API_KEY')
        self.use_firecrawl = self.config.get('immowelt_settings', {}).get('use_firecrawl', True)
        
        if self.use_firecrawl and self.firecrawl_api_key and FIRECRAWL_AVAILABLE:
            try:
                self.firecrawl = FirecrawlApp(api_key=self.firecrawl_api_key)
                self.logger.info("✅ Firecrawl API инициализирован для Immowelt")
            except Exception as e:
                self.logger.error(f"❌ Ошибка инициализации Firecrawl: {e}")
                self.firecrawl = None
                self.use_firecrawl = False
        else:
            self.firecrawl = None
            if self.use_firecrawl and not self.firecrawl_api_key:
                self.logger.warning("⚠️  FIRECRAWL_API_KEY не установлен в ENV")
                self.use_firecrawl = False
        
        # Создаем новую session для Immowelt с улучшенной имитацией браузера
        self.session = requests.Session()
        
        # Более полный набор headers для имитации реального браузера
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'DNT': '1',
        })
        
        self.logger.info(f"Инициализирован парсер для Immowelt.de (Firecrawl: {'✅' if self.use_firecrawl else '❌'})")
    
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
                wait_for=2000  # Ждем 2 секунды для загрузки JavaScript
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
        
        # Сначала пробуем Firecrawl для Immowelt
        if self.use_firecrawl and 'immowelt.de' in url:
            soup = self.get_page_with_firecrawl(url)
            if soup:
                return soup
            else:
                self.logger.warning("⚠️  Firecrawl не сработал, пробуем обычный запрос...")
        
        # Fallback на обычный HTTP запрос
        return super().get_page(url, retries)
    
    def get_initial_cookies(self):
        """Получение начальных cookies с главной страницы Immowelt"""
        try:
            self.logger.info("Получение начальных cookies для Immowelt...")
            
            # Добавляем задержку для имитации реального пользователя
            time.sleep(1)
            
            # Сначала заходим на главную
            response = self.session.get('https://www.immowelt.de/', timeout=30, allow_redirects=True)
            
            self.logger.debug(f"Статус главной страницы: {response.status_code}")
            self.logger.debug(f"Получено cookies: {len(self.session.cookies)}")
            
            if response.status_code == 200:
                self.logger.info("Cookies для Immowelt получены успешно")
                
                # Обновляем Referer для последующих запросов
                self.session.headers['Referer'] = 'https://www.immowelt.de/'
                return True
            else:
                self.logger.warning(f"Не удалось получить cookies для Immowelt: {response.status_code}")
                # Пытаемся получить больше информации
                self.logger.debug(f"Response text (first 500 chars): {response.text[:500]}")
                return False
        except Exception as e:
            self.logger.warning(f"Ошибка при получении cookies для Immowelt: {e}")
            return False
    
    def extract_listing_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Извлечение ссылок на объявления из списка Immowelt (только с меткой Neu)"""
        links = []
        
        # Ищем все элементы со значком "Neu" - пробуем разные варианты
        neu_elements = soup.find_all('span', attrs={'data-testid': 'cardmfe-tag-testid-new'})
        
        # Если не нашли через data-testid, ищем по тексту
        if not neu_elements:
            neu_elements = soup.find_all('span', string=lambda x: x and x.strip() == 'Neu')
        
        self.logger.info(f"Найдено {len(neu_elements)} значков 'Neu' на странице")
        
        # Для каждого значка "Neu" ищем ближайшую ссылку на объявление
        for neu_span in neu_elements:
            # Поднимаемся вверх по дереву до контейнера карточки
            container = neu_span
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
                            full_url = 'https://www.immowelt.de' + href
                        else:
                            full_url = urljoin(base_url, href)
                        
                        # Добавляем только уникальные ссылки
                        if full_url not in links:
                            links.append(full_url)
                            self.logger.debug(f"Найдено новое объявление: {full_url}")
                        break
        
        self.logger.info(f"Найдено {len(links)} НОВЫХ объявлений с меткой 'Neu' на Immowelt")
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
                'span.css-9wpf20',  # Основной селектор для цены на Immowelt
                'div[data-test="price"] strong',
                '.hardfact_value strong',
                'strong[data-test="kaltmiete"]',
                '.price_value'
            ]
            
            for selector in price_selectors:
                price_elem = soup.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    # Убираем все кроме цифр, точек и запятых
                    price_text = re.sub(r'[^\d,.]', '', price_text)
                    
                    # В немецком формате: 753.71 € = 753 евро 71 цент
                    # Заменяем точку на ничего (разделитель тысяч), запятую на точку (десятичная часть)
                    if ',' in price_text:
                        # Если есть запятая, это десятичный разделитель
                        price_text = price_text.replace('.', '').replace(',', '.')
                    # Если нет запятой, точка - это разделитель тысяч или десятичный
                    elif '.' in price_text:
                        parts = price_text.split('.')
                        if len(parts) == 2 and len(parts[1]) == 2:
                            # 753.71 - это 753 евро с центами
                            price_text = price_text  # оставляем как есть
                        else:
                            # 1.000 - это разделитель тысяч
                            price_text = price_text.replace('.', '')
                    
                    try:
                        price = int(float(price_text))
                        break
                    except ValueError:
                        continue
            
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
                'span.css-wpv6zq',  # Основной селектор для адреса на Immowelt
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
            
            # Для Immowelt дата не нужна - мы фильтруем по значку "Neu"
            # Все найденные объявления уже новые, поэтому используем сегодняшнюю дату
            listing_date = datetime.now()
            self.logger.debug("Для Immowelt используем текущую дату (фильтр по значку Neu)")
            
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
                'description': description[:500] if description else "",
                'url': url,
                'date_posted': listing_date.isoformat() if listing_date else None,
                'date_found': datetime.now().isoformat(),
                'hash': listing_hash
            }
            
            self.logger.info(f"✅ Извлечены данные Immowelt (NEW): {title} - {price}€ - {location}")
            return listing_data
            
        except Exception as e:
            self.logger.error(f"Ошибка при извлечении данных из Immowelt {url}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None

    def parse_listings(self):
        """Основной метод парсинга с ограничением для Immowelt"""
        # Временно переопределяем max_listings_per_run для Immowelt
        original_max = self.config.get('settings', {}).get('max_listings_per_run', 50)
        immowelt_max = self.config.get('settings', {}).get('max_listings_immowelt', 2)
        
        # Устанавливаем лимит для Immowelt
        self.config['settings']['max_listings_per_run'] = immowelt_max
        self.logger.info(f"Ограничение для Immowelt: максимум {immowelt_max} объявлений")
        
        try:
            # Вызываем родительский метод
            result = super().parse_listings()
            return result
        finally:
            # Восстанавливаем оригинальное значение
            self.config['settings']['max_listings_per_run'] = original_max


if __name__ == "__main__":
    # Тестовый запуск
    parser = ImmoweltParser()
    parser.parse_listings()
