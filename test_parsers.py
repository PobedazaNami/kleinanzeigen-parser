#!/usr/bin/env python3
"""
Тестовый скрипт для проверки парсеров
"""

import sys
import os

# Добавляем текущую директорию в PYTHONPATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_kleinanzeigen():
    """Тест парсера Kleinanzeigen"""
    print("=" * 60)
    print("Тестирование Kleinanzeigen Parser")
    print("=" * 60)
    
    try:
        from kleinanzeigen_parser import KleinanzeigenParser
        
        parser = KleinanzeigenParser("config.json")
        print("✓ Парсер успешно инициализирован")
        
        # Проверяем подключение к базе данных
        parser.cursor.execute("SELECT COUNT(*) FROM listings")
        count = parser.cursor.fetchone()[0]
        print(f"✓ База данных подключена. Найдено {count} объявлений")
        
        # Проверяем Telegram
        if parser.bot:
            print("✓ Telegram бот подключен")
        else:
            print("⚠ Telegram бот не настроен")
        
        return True
        
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_immowelt():
    """Тест парсера Immowelt"""
    print("\n" + "=" * 60)
    print("Тестирование Immowelt Parser")
    print("=" * 60)
    
    try:
        from immowelt_parser import ImmoweltParser
        
        parser = ImmoweltParser("config.json")
        print("✓ Парсер успешно инициализирован")
        
        # Проверяем подключение к базе данных
        parser.cursor.execute("SELECT COUNT(*) FROM listings WHERE id LIKE 'immowelt_%'")
        count = parser.cursor.fetchone()[0]
        print(f"✓ База данных подключена. Найдено {count} объявлений Immowelt")
        
        # Проверяем Telegram
        if parser.bot:
            print("✓ Telegram бот подключен")
        else:
            print("⚠ Telegram бот не настроен")
        
        return True
        
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_url_detection():
    """Тест определения типа сайта по URL"""
    print("\n" + "=" * 60)
    print("Тестирование определения типа сайта")
    print("=" * 60)
    
    from main import ProductionRunner
    runner = ProductionRunner()
    
    test_urls = [
        ("https://www.kleinanzeigen.de/s-wohnung-mieten/darmstadt/k0c203l4888", "kleinanzeigen"),
        ("https://www.immowelt.de/liste/darmstadt/wohnungen/mieten", "immowelt"),
        ("https://www.ebay-kleinanzeigen.de/s-wohnung/berlin/k0c203", "kleinanzeigen"),
    ]
    
    all_correct = True
    for url, expected_type in test_urls:
        detected_type = runner.detect_site_type(url)
        status = "✓" if detected_type == expected_type else "✗"
        print(f"{status} {url[:50]}... -> {detected_type}")
        if detected_type != expected_type:
            all_correct = False
            print(f"  Ожидалось: {expected_type}, получено: {detected_type}")
    
    return all_correct


def main():
    """Главная функция"""
    print("\n🧪 Запуск тестов парсеров\n")
    
    results = []
    
    # Тест Kleinanzeigen
    results.append(("Kleinanzeigen Parser", test_kleinanzeigen()))
    
    # Тест Immowelt
    results.append(("Immowelt Parser", test_immowelt()))
    
    # Тест определения URL
    results.append(("URL Detection", test_url_detection()))
    
    # Итоги
    print("\n" + "=" * 60)
    print("Результаты тестов")
    print("=" * 60)
    
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n✅ Все тесты пройдены успешно!")
        return 0
    else:
        print("\n❌ Некоторые тесты не прошли")
        return 1


if __name__ == "__main__":
    sys.exit(main())
