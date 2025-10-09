#!/usr/bin/env python3
"""
Миграция базы данных - добавляет колонку parser_source
"""
import sqlite3
import sys

def migrate_database(db_path='data/listings.db'):
    """Добавляет колонку parser_source если её нет"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем существующую структуру
        cursor.execute("PRAGMA table_info(listings)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'parser_source' not in columns:
            print("📝 Добавляем колонку parser_source...")
            cursor.execute("ALTER TABLE listings ADD COLUMN parser_source TEXT DEFAULT 'kleinanzeigen'")
            conn.commit()
            print("✅ Колонка parser_source успешно добавлена!")
        else:
            print("✅ Колонка parser_source уже существует")
        
        # Показываем статистику
        cursor.execute("SELECT COUNT(*) FROM listings")
        total = cursor.fetchone()[0]
        print(f"\n📊 Всего записей в базе: {total}")
        
        cursor.execute("SELECT COUNT(*), parser_source FROM listings GROUP BY parser_source")
        for count, source in cursor.fetchall():
            print(f"   - {source}: {count}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        return False

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'data/listings.db'
    success = migrate_database(db_path)
    sys.exit(0 if success else 1)
