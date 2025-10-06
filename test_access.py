#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки доступа к Kleinanzeigen
"""

import requests
from bs4 import BeautifulSoup
import json

def test_kleinanzeigen_access():
    """Проверка доступа к kleinanzeigen.de"""
    
    print("=" * 60)
    print("Тест доступа к Kleinanzeigen")
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
    
    print(f"\n📍 URL для тестирования: {kleinanzeigen_url}\n")
    
    # Создаем сессию с headers
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'DNT': '1'
    })
    
    # Тест 1: Проверка главной страницы
    print("🔍 Тест 1: Доступ к главной странице kleinanzeigen.de...")
    try:
        response = session.get('https://www.kleinanzeigen.de/', timeout=10)
        print(f"   Статус: {response.status_code}")
        print(f"   Размер ответа: {len(response.text)} символов")
        
        if response.status_code == 200:
            print("   ✅ Доступ к главной странице получен")
        else:
            print(f"   ❌ Ошибка: HTTP {response.status_code}")
            
        # Проверка на блокировку
        text_lower = response.text.lower()
        blocking_keywords = ['captcha', 'access denied', 'blocked', 'cloudflare', 'bot detection']
        found_blocks = [kw for kw in blocking_keywords if kw in text_lower]
        
        if found_blocks:
            print(f"   ⚠️  Обнаружены признаки блокировки: {', '.join(found_blocks)}")
            print(f"   📄 Первые 500 символов ответа:")
            print(f"   {response.text[:500]}")
        else:
            print("   ✅ Признаков блокировки не обнаружено")
            
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
    
    print()
    
    # Тест 2: Проверка поисковой страницы
    print("🔍 Тест 2: Доступ к поисковой странице...")
    try:
        response = session.get(kleinanzeigen_url, timeout=10)
        print(f"   Статус: {response.status_code}")
        print(f"   Размер ответа: {len(response.text)} символов")
        
        if response.status_code == 200:
            print("   ✅ Доступ к поисковой странице получен")
            
            # Парсим страницу
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем объявления по разным селекторам
            selectors = [
                ('article h2 a', 'article h2 a'),
                ('a[href*="/s-anzeige/"]', 'ссылки с /s-anzeige/'),
                ('.aditem-main a', '.aditem-main a'),
                ('article', 'теги <article>'),
                ('.aditem', 'элементы с классом .aditem')
            ]
            
            print("\n   📊 Поиск элементов объявлений:")
            for selector, description in selectors:
                elements = soup.select(selector)
                count = len(elements)
                if count > 0:
                    print(f"   ✅ {description}: найдено {count} элементов")
                else:
                    print(f"   ❌ {description}: не найдено")
            
            # Проверяем структуру страницы
            print("\n   📋 Структура страницы:")
            print(f"   - Найдено тегов <article>: {len(soup.find_all('article'))}")
            print(f"   - Найдено ссылок всего: {len(soup.find_all('a'))}")
            print(f"   - Найдено тегов <h1>: {len(soup.find_all('h1'))}")
            print(f"   - Найдено тегов <h2>: {len(soup.find_all('h2'))}")
            
            # Сохраняем HTML для анализа
            with open('/tmp/kleinanzeigen_page.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            print("\n   💾 HTML страницы сохранен в /tmp/kleinanzeigen_page.html")
            
        elif response.status_code == 403:
            print("   ❌ Ошибка 403 Forbidden - доступ запрещен")
            print("   💡 Возможные причины:")
            print("      - Блокировка по IP")
            print("      - Определение как бот")
            print("      - Требуется прокси")
        elif response.status_code == 429:
            print("   ❌ Ошибка 429 Too Many Requests - слишком много запросов")
        else:
            print(f"   ❌ Ошибка: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
    
    print("\n" + "=" * 60)
    print("Тестирование завершено")
    print("=" * 60)

if __name__ == '__main__':
    test_kleinanzeigen_access()
