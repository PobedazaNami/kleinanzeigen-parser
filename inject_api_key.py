#!/usr/bin/env python3
"""
Инжектит Firecrawl API ключ в config.json из переменной окружения
"""
import json
import os
import sys

def inject_api_key():
    api_key = os.getenv('FIRECRAWL_API_KEY')
    if not api_key:
        print("⚠️  FIRECRAWL_API_KEY не установлен")
        return
    
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    config['firecrawl_api_key'] = api_key
    
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=2)
    
    print("✅ Firecrawl API ключ добавлен в config.json")

if __name__ == '__main__':
    inject_api_key()
