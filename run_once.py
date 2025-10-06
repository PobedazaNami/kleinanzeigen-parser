#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Запуск парсера в тестовом режиме (один проход)
"""

import sys
import json

from kleinanzeigen_parser import KleinanzeigenParser

def main():
    print("=" * 60)
    print("ЗАПУСК ПАРСЕРА KLEINANZEIGEN")
    print("=" * 60)
    
    # Определяем путь к конфигу
    try:
        config_path = 'config.json'
        with open(config_path, 'r', encoding='utf-8') as f:
            test_config = json.load(f)
        print("✅ Используется config.json\n")
    except FileNotFoundError:
        config_path = 'config.example.json'
        print("⚠️  config.json не найден, используется config.example.json\n")
    
    # Создаем парсер
    parser = KleinanzeigenParser(config_path)
    
    # Запускаем один цикл парсинга
    print("🚀 Запуск парсинга...\n")
    parser.parse_listings()
    
    print("\n" + "=" * 60)
    print("✅ ПАРСИНГ ЗАВЕРШЕН")
    print("=" * 60)

if __name__ == '__main__':
    main()
