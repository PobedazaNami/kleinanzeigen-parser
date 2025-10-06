#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки доступа к Immowelt
"""

import requests
from bs4 import BeautifulSoup
import json

def test_immowelt_access():
    """Проверка доступа к immowelt.de"""
    
    print("=" * 60)
    print("Тест доступа к Immowelt")
    print("=" * 60)
    
    # Читаем URL из конфига
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        with open('config.example.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    
    # Берем URL для immowelt
    search_urls = config.get('search_urls', [])
    immowelt_url = None
    for url in search_urls:
        if 'immowelt.de' in url:
            immowelt_url = url
            break
    
    if not immowelt_url:
        print("❌ URL для Immowelt не найден в конфиге")
        return
    
    print(f"\n📍 URL для тестирования: {immowelt_url}\n")
    
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
    print("🔍 Тест 1: Доступ к главной странице immowelt.de...")
    try:
        response = session.get('https://www.immowelt.de/', timeout=10, allow_redirects=True)
        print(f"   Статус: {response.status_code}")
        print(f"   Финальный URL: {response.url}")
        print(f"   Размер ответа: {len(response.text)} символов")
        
        if response.status_code == 200:
            print("   ✅ Доступ к главной странице получен")
        else:
            print(f"   ❌ Ошибка: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
    
    print()
    
    # Тест 2: Проверка поисковой страницы
    print("🔍 Тест 2: Доступ к поисковой странице...")
    try:
        response = session.get(immowelt_url, timeout=10, allow_redirects=True)
        print(f"   Статус: {response.status_code}")
        print(f"   Финальный URL: {response.url}")
        print(f"   Редиректы: {len(response.history)} шт.")
        if response.history:
            print(f"   Цепочка редиректов:")
            for i, r in enumerate(response.history):
                print(f"      {i+1}. {r.status_code} -> {r.url}")
        
        print(f"   Размер ответа: {len(response.text)} символов")
        
        if response.status_code == 200:
            print("   ✅ Доступ к поисковой странице получен")
            
            # Парсим страницу
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем объявления по разным селекторам
            selectors = [
                ('a[href*="/expose/"]', 'ссылки с /expose/'),
                ('article', 'теги <article>'),
                ('.listitem', 'элементы с классом .listitem'),
                ('.listcontent', 'элементы с классом .listcontent'),
                ('[data-test="result-item"]', 'элементы с data-test="result-item"'),
                ('[data-test*="estate"]', 'элементы с data-test содержащим estate'),
            ]
            
            print("\n   📊 Поиск элементов объявлений:")
            for selector, description in selectors:
                elements = soup.select(selector)
                count = len(elements)
                if count > 0:
                    print(f"   ✅ {description}: найдено {count} элементов")
                    # Показываем первые 3 ссылки для /expose/
                    if '/expose/' in selector and count > 0:
                        print(f"      Примеры ссылок:")
                        for i, elem in enumerate(elements[:3]):
                            href = elem.get('href', '')
                            print(f"         {i+1}. {href[:80]}")
                else:
                    print(f"   ❌ {description}: не найдено")
            
            # Проверяем структуру страницы
            print("\n   📋 Структура страницы:")
            print(f"   - Найдено тегов <article>: {len(soup.find_all('article'))}")
            print(f"   - Найдено тегов <div>: {len(soup.find_all('div'))}")
            print(f"   - Найдено ссылок всего: {len(soup.find_all('a'))}")
            
            # Ищем признаки React/Vue приложения
            if 'react' in response.text.lower() or '__NEXT_DATA__' in response.text:
                print("\n   ⚠️  Страница использует React/Next.js - может требоваться JavaScript")
            if 'vue' in response.text.lower():
                print("\n   ⚠️  Страница использует Vue.js - может требоваться JavaScript")
            
            # Сохраняем HTML для анализа
            with open('/tmp/immowelt_page.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            print("\n   💾 HTML страницы сохранен в /tmp/immowelt_page.html")
            
        elif response.status_code == 403:
            print("   ❌ Ошибка 403 Forbidden - доступ запрещен")
        elif response.status_code == 429:
            print("   ❌ Ошибка 429 Too Many Requests - слишком много запросов")
        else:
            print(f"   ❌ Ошибка: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Тестирование завершено")
    print("=" * 60)

if __name__ == '__main__':
    test_immowelt_access()
