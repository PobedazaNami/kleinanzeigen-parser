#!/usr/bin/env python3
"""
Утилита для управления базой данных парсера Kleinanzeigen
"""

import sqlite3
import json
from datetime import datetime
import sys

class DatabaseManager:
    """Менеджер базы данных"""
    
    def __init__(self, db_path: str = "listings.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
    
    def show_stats(self):
        """Показать статистику базы данных"""
        print("=== Статистика базы данных ===\n")
        
        # Общее количество объявлений
        self.cursor.execute("SELECT COUNT(*) FROM listings")
        total = self.cursor.fetchone()[0]
        print(f"Всего объявлений: {total}")
        
        # Количество уведомлений
        self.cursor.execute("SELECT COUNT(*) FROM listings WHERE notified = 1")
        notified = self.cursor.fetchone()[0]
        print(f"Отправлено уведомлений: {notified}")
        
        # Средняя цена
        self.cursor.execute("SELECT AVG(price) FROM listings WHERE price IS NOT NULL")
        avg_price = self.cursor.fetchone()[0]
        if avg_price:
            print(f"Средняя цена: {avg_price:.0f}€")
        
        # Диапазон цен
        self.cursor.execute("SELECT MIN(price), MAX(price) FROM listings WHERE price IS NOT NULL")
        min_price, max_price = self.cursor.fetchone()
        if min_price and max_price:
            print(f"Диапазон цен: {min_price}€ - {max_price}€")
        
        # Последнее объявление
        self.cursor.execute("SELECT title, date_found FROM listings ORDER BY date_found DESC LIMIT 1")
        result = self.cursor.fetchone()
        if result:
            title, date_found = result
            print(f"Последнее объявление: {title} ({date_found})")
        
        print()
    
    def list_recent(self, limit: int = 10):
        """Показать последние объявления"""
        print(f"=== Последние {limit} объявлений ===\n")
        
        self.cursor.execute("""
            SELECT title, price, size, location, date_found, notified 
            FROM listings 
            ORDER BY date_found DESC 
            LIMIT ?
        """, (limit,))
        
        results = self.cursor.fetchall()
        
        for i, (title, price, size, location, date_found, notified) in enumerate(results, 1):
            status = "✅" if notified else "❌"
            price_str = f"{price}€" if price else "Н/Д"
            size_str = f"{size}м²" if size else "Н/Д"
            
            print(f"{i}. {status} {title}")
            print(f"   💰 {price_str} | 📐 {size_str} | 📍 {location}")
            print(f"   🕒 {date_found}")
            print()
    
    def search_listings(self, query: str, limit: int = 10):
        """Поиск объявлений по ключевому слову"""
        print(f"=== Результаты поиска: '{query}' ===\n")
        
        self.cursor.execute("""
            SELECT title, price, size, location, url, date_found 
            FROM listings 
            WHERE title LIKE ? OR description LIKE ? OR location LIKE ?
            ORDER BY date_found DESC 
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
        
        results = self.cursor.fetchall()
        
        if not results:
            print("Ничего не найдено")
            return
        
        for i, (title, price, size, location, url, date_found) in enumerate(results, 1):
            price_str = f"{price}€" if price else "Н/Д"
            size_str = f"{size}м²" if size else "Н/Д"
            
            print(f"{i}. {title}")
            print(f"   💰 {price_str} | 📐 {size_str} | 📍 {location}")
            print(f"   🔗 {url}")
            print(f"   🕒 {date_found}")
            print()
    
    def clean_old_listings(self, days: int = 30):
        """Очистка старых объявлений"""
        from datetime import datetime, timedelta
        
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        self.cursor.execute("SELECT COUNT(*) FROM listings WHERE date_found < ?", (cutoff_date,))
        count = self.cursor.fetchone()[0]
        
        if count == 0:
            print(f"Нет объявлений старше {days} дней")
            return
        
        confirm = input(f"Удалить {count} объявлений старше {days} дней? (y/N): ").lower()
        if confirm in ['y', 'yes', 'да']:
            self.cursor.execute("DELETE FROM listings WHERE date_found < ?", (cutoff_date,))
            self.conn.commit()
            print(f"Удалено {count} старых объявлений")
        else:
            print("Отменено")
    
    def export_to_json(self, filename: str = None):
        """Экспорт данных в JSON"""
        if not filename:
            filename = f"listings_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        self.cursor.execute("SELECT * FROM listings")
        results = self.cursor.fetchall()
        
        # Получаем названия колонок
        columns = [description[0] for description in self.cursor.description]
        
        # Конвертируем в список словарей
        data = []
        for row in results:
            data.append(dict(zip(columns, row)))
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"Экспортировано {len(data)} объявлений в файл: {filename}")
    
    def reset_notifications(self):
        """Сброс флагов уведомлений"""
        self.cursor.execute("SELECT COUNT(*) FROM listings WHERE notified = 1")
        count = self.cursor.fetchone()[0]
        
        if count == 0:
            print("Нет объявлений с установленными флагами уведомлений")
            return
        
        confirm = input(f"Сбросить флаги уведомлений для {count} объявлений? (y/N): ").lower()
        if confirm in ['y', 'yes', 'да']:
            self.cursor.execute("UPDATE listings SET notified = 0")
            self.conn.commit()
            print(f"Флаги уведомлений сброшены для {count} объявлений")
        else:
            print("Отменено")
    
    def close(self):
        """Закрыть соединение с базой данных"""
        self.conn.close()

def main():
    """Главная функция"""
    if len(sys.argv) < 2:
        print("Утилита управления базой данных Kleinanzeigen Parser")
        print("\nИспользование:")
        print("  python db_manager.py stats           - Показать статистику")
        print("  python db_manager.py recent [N]      - Показать последние N объявлений (по умолчанию 10)")
        print("  python db_manager.py search <query>  - Поиск объявлений")
        print("  python db_manager.py clean [days]    - Очистить объявления старше N дней (по умолчанию 30)")
        print("  python db_manager.py export [file]   - Экспорт в JSON")
        print("  python db_manager.py reset-notify    - Сбросить флаги уведомлений")
        return
    
    db = DatabaseManager()
    
    try:
        command = sys.argv[1].lower()
        
        if command == "stats":
            db.show_stats()
        
        elif command == "recent":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            db.list_recent(limit)
        
        elif command == "search":
            if len(sys.argv) < 3:
                print("Укажите поисковый запрос")
                return
            query = " ".join(sys.argv[2:])
            db.search_listings(query)
        
        elif command == "clean":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            db.clean_old_listings(days)
        
        elif command == "export":
            filename = sys.argv[2] if len(sys.argv) > 2 else None
            db.export_to_json(filename)
        
        elif command == "reset-notify":
            db.reset_notifications()
        
        else:
            print(f"Неизвестная команда: {command}")
            
    except Exception as e:
        print(f"Ошибка: {e}")
    
    finally:
        db.close()

if __name__ == "__main__":
    main()