#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Полный тест парсинга с использованием реального парсера
"""

import sys
import json
import logging

# Настраиваем логирование на DEBUG уровень
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from kleinanzeigen_parser import KleinanzeigenParser

def test_full_parsing():
    """Тестируем полный цикл парсинга"""
    
    print("=" * 60)
    print("ПОЛНЫЙ ТЕСТ ПАРСИНГА KLEINANZEIGEN")
    print("=" * 60)
    
    # Загружаем конфигурацию
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        with open('config.example.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    
    # Отключаем отправку в Telegram для теста
    # Сохраняем временный конфиг
    import tempfile
    config['telegram']['bot_token'] = None
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(config, f)
        temp_config_path = f.name
    
    # Создаем парсер
    parser = KleinanzeigenParser(temp_config_path)
    
    # Берем первый URL для kleinanzeigen
    search_urls = config.get('search_urls', [])
    kleinanzeigen_url = None
    for url in search_urls:
        if 'kleinanzeigen.de' in url:
            kleinanzeigen_url = url
            break
    
    if not kleinanzeigen_url:
        print("❌ URL для Kleinanzeigen не найден")
        return
    
    print(f"\n📍 URL для парсинга: {kleinanzeigen_url}\n")
    
    # Получаем страницу со списком
    print("1️⃣ Получение списка объявлений...")
    soup = parser.get_page(kleinanzeigen_url)
    if not soup:
        print("❌ Не удалось получить страницу")
        return
    
    print("✅ Страница получена\n")
    
    # Извлекаем ссылки
    print("2️⃣ Извлечение ссылок на объявления...")
    listing_links = parser.extract_listing_links(soup, kleinanzeigen_url)
    print(f"✅ Найдено {len(listing_links)} объявлений\n")
    
    if not listing_links:
        print("❌ Ссылки не найдены")
        return
    
    # Берем первые 3 объявления для теста
    test_count = min(3, len(listing_links))
    print(f"3️⃣ Тестирую парсинг первых {test_count} объявлений:\n")
    
    success_count = 0
    error_count = 0
    skipped_by_date_count = 0
    
    for i, link in enumerate(listing_links[:test_count]):
        print(f"\n{'=' * 60}")
        print(f"Объявление {i+1}/{test_count}")
        print(f"URL: {link}")
        print('=' * 60)
        
        # Получаем страницу объявления
        listing_soup = parser.get_page(link)
        if not listing_soup:
            print("❌ Не удалось получить страницу объявления")
            error_count += 1
            continue
        
        # Извлекаем данные
        listing_data = parser.extract_listing_data(listing_soup, link)
        
        if listing_data is None:
            print("❌ Ошибка при извлечении данных")
            error_count += 1
        elif listing_data == "SKIPPED_BY_DATE":
            print("⏩ Объявление пропущено по дате (не сегодня)")
            skipped_by_date_count += 1
        else:
            print("✅ Данные успешно извлечены:")
            print(f"   Заголовок: {listing_data.get('title')}")
            print(f"   Цена: {listing_data.get('price')} €")
            print(f"   Площадь: {listing_data.get('size')} m²")
            print(f"   Комнаты: {listing_data.get('rooms')}")
            print(f"   Локация: {listing_data.get('location')}")
            print(f"   Дата публикации: {listing_data.get('date_posted')}")
            
            # Проверяем фильтры
            if parser.check_filters(listing_data):
                print("   ✅ Объявление прошло фильтры")
                success_count += 1
            else:
                print("   ⚠️  Объявление не прошло фильтры")
                success_count += 1  # Всё равно считаем успешным парсингом
    
    print(f"\n{'=' * 60}")
    print("РЕЗУЛЬТАТЫ ТЕСТА")
    print('=' * 60)
    print(f"Успешно обработано: {success_count}")
    print(f"Пропущено по дате: {skipped_by_date_count}")
    print(f"Ошибок: {error_count}")
    print('=' * 60)
    
    if error_count == test_count:
        print("\n❌ ВСЕ объявления вызвали ошибки!")
        print("Возможные причины:")
        print("  - Проблемы с парсингом даты")
        print("  - Изменилась структура сайта")
        print("  - Блокировка доступа")
    elif skipped_by_date_count == test_count:
        print("\n⚠️  ВСЕ объявления пропущены по дате!")
        print("Возможные причины:")
        print("  - Настройка 'only_today: true', но объявления не сегодняшние")
        print("  - Проблемы с парсингом даты")
        print("  - Неправильный timezone")
    elif success_count > 0:
        print(f"\n✅ Парсинг работает! Успешно обработано {success_count} объявлений")

if __name__ == '__main__':
    test_full_parsing()
