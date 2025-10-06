#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки парсинга отдельных объявлений
"""

import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

def test_single_listing():
    """Тестируем парсинг одного объявления"""
    
    print("=" * 60)
    print("Тест парсинга отдельного объявления")
    print("=" * 60)
    
    # Читаем URL из конфига
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        with open('config.example.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    
    # Берем первый URL для kleinanzeigen
    search_urls = config.get('search_urls', [])
    kleinanzeigen_url = None
    for url in search_urls:
        if 'kleinanzeigen.de' in url:
            kleinanzeigen_url = url
            break
    
    if not kleinanzeigen_url:
        print("❌ URL для Kleinanzeigen не найден в конфиге")
        return
    
    # Создаем сессию
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
    })
    
    # Получаем список объявлений
    print(f"\n📍 Получаю список объявлений с: {kleinanzeigen_url}\n")
    response = session.get(kleinanzeigen_url, timeout=10)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Находим ссылки на объявления
    links = []
    for element in soup.select('article h2 a'):
        href = element.get('href')
        if href and '/s-anzeige/' in href:
            if not href.startswith('http'):
                href = 'https://www.kleinanzeigen.de' + href
            links.append(href)
    
    print(f"✅ Найдено {len(links)} объявлений\n")
    
    if not links:
        print("❌ Не удалось найти объявления")
        return
    
    # Берем первое объявление для теста
    test_url = links[0]
    print(f"🔍 Тестирую парсинг объявления: {test_url}\n")
    
    # Получаем страницу объявления
    try:
        response = session.get(test_url, timeout=10)
        print(f"   Статус: {response.status_code}")
        print(f"   Размер ответа: {len(response.text)} символов\n")
        
        if response.status_code != 200:
            print(f"   ❌ Ошибка HTTP {response.status_code}")
            return
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Извлекаем данные
        print("📊 Извлечение данных:\n")
        
        # Заголовок
        title_elem = soup.find('h1')
        title = title_elem.get_text(strip=True) if title_elem else None
        print(f"   Заголовок: {title}")
        
        # Цена
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
                print(f"   Цена (селектор {selector}): {price_text}")
                price_match = re.search(r'(\d+(?:\.\d+)?)', price_text.replace('.', '').replace(',', ''))
                if price_match:
                    price = int(float(price_match.group(1)))
                break
        
        print(f"   Цена (обработанная): {price}")
        
        # Дата
        print("\n   🗓️  Поиск даты публикации:")
        
        # Проверяем #viewad-extra-info
        viewad_info = soup.select_one('#viewad-extra-info')
        if viewad_info:
            info_text = viewad_info.get_text()
            print(f"      #viewad-extra-info: {info_text[:200]}")
            date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})', info_text)
            if date_match:
                print(f"      ✅ Найдена дата: {date_match.group(1)}")
            else:
                print(f"      ❌ Дата не найдена в #viewad-extra-info")
        else:
            print(f"      ❌ Элемент #viewad-extra-info не найден")
        
        # Другие селекторы
        date_selectors = [
            '.aditem-details--top--right',
            '.aditem-addon',  
            '.ad-keyfacts',
            '.aditem-main--top--right'
        ]
        
        for selector in date_selectors:
            date_elem = soup.select_one(selector)
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                print(f"      {selector}: {date_text[:100]}")
                date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})', date_text)
                if date_match:
                    print(f"         ✅ Найдена дата: {date_match.group(1)}")
        
        # Размер и комнаты
        print("\n   🏠 Поиск характеристик:")
        details_section = soup.find('dl') or soup.find('div', class_='addetailslist')
        if details_section:
            text = details_section.get_text()
            print(f"      Текст из деталей: {text[:200]}")
            
            # Новая логика парсинга по структуре HTML
            size = None
            rooms = None
            
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
                            print(f"      ✅ Площадь (из span): {size} m²")
                
                # Поиск количества комнат
                if 'zimmer' in item_text and 'schlafzimmer' not in item_text and 'badezimmer' not in item_text:
                    value_elem = item.find('span', class_='addetailslist--detail--value')
                    if value_elem:
                        value_text = value_elem.get_text().strip()
                        rooms_match = re.search(r'(\d+(?:[.,]\d+)?)', value_text)
                        if rooms_match:
                            rooms = rooms_match.group(1).replace(',', '.')
                            print(f"      ✅ Комнаты (из span): {rooms}")
            
            if not size:
                size_match = re.search(r'(\d+)\s*m²', text)
                if size_match:
                    print(f"      ✅ Площадь: {size_match.group(1)} m²")
                else:
                    print(f"      ❌ Площадь не найдена")
            
            if not rooms:
                # Более гибкое регулярное выражение
                rooms_match = re.search(r'Zimmer\s+(\d+(?:[.,]\d+)?)', text, re.IGNORECASE)
                if not rooms_match:
                    rooms_match = re.search(r'(\d+(?:[.,]\d+)?)\s+Zimmer', text, re.IGNORECASE)
                if rooms_match:
                    print(f"      ✅ Комнаты (regex): {rooms_match.group(1)}")
                else:
                    print(f"      ❌ Количество комнат не найдено")
        else:
            print(f"      ❌ Секция с деталями не найдена")
        
        # Сохраняем HTML
        with open('/tmp/listing_page.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print("\n   💾 HTML объявления сохранен в /tmp/listing_page.html")
        
        print("\n" + "=" * 60)
        print("✅ Тест завершен")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_single_listing()
