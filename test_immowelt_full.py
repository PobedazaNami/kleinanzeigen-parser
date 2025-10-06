#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тест полного парсинга Immowelt с ограничением до 2 объявлений
"""

from immowelt_parser import ImmoweltParser
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

print("=" * 60)
print("ТЕСТ ПОЛНОГО ПАРСИНГА IMMOWELT (ОГРАНИЧЕНИЕ: 2 ОБЪЯВЛЕНИЯ)")
print("=" * 60)

# Создаем парсер Immowelt
parser = ImmoweltParser("config.json")

print(f"\n✅ Immowelt парсер создан")
print(f"Настройка max_listings_immowelt: {parser.config.get('settings', {}).get('max_listings_immowelt', 'не найдена')}")

# Запускаем парсинг
print("\n🚀 Запуск парсинга...\n")
parser.parse_listings()

print("\n" + "=" * 60)
print("✅ ТЕСТ ЗАВЕРШЕН")
print("=" * 60)
