#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тест парсера Immowelt
"""

from immowelt_parser import ImmoweltParser
import logging

logging.basicConfig(level=logging.INFO)

print("=" * 60)
print("ТЕСТ IMMOWELT PARSER")
print("=" * 60)

# Создаем парсер Immowelt
parser = ImmoweltParser("config.json")

print("\n✅ Immowelt парсер создан")
print(f"Session headers: {dict(parser.session.headers)}")
print(f"Accept-Encoding: {parser.session.headers.get('Accept-Encoding')}")

# Получаем одну страницу
url = 'https://www.immowelt.de/liste/darmstadt/wohnungen/mieten?d=true&sd=DESC&sf=TIMESTAMP&sp=1'
print(f"\n🔍 Получаю страницу: {url}")

soup = parser.get_page(url)
if soup:
    print("✅ Страница получена")
    
    # Извлекаем ссылки
    links = parser.extract_listing_links(soup, url)
    print(f"\n📊 Найдено объявлений: {len(links)}")
    
    if links:
        print("\nПримеры ссылок:")
        for i, link in enumerate(links[:5]):
            print(f"   {i+1}. {link}")
    else:
        print("\n❌ Объявления не найдены")
        # Проверяем теги
        print("\nПроверка HTML:")
        print(f"   <div> тегов: {len(soup.find_all('div'))}")
        print(f"   <a> тегов: {len(soup.find_all('a'))}")
        print(f"   Ссылок с /expose/: {len([a for a in soup.find_all('a', href=True) if '/expose/' in a.get('href', '')])}")
else:
    print("❌ Не удалось получить страницу")

print("\n" + "=" * 60)
