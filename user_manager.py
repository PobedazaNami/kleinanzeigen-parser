#!/usr/bin/env python3
"""
User Management System (MongoDB-backed)
- Управление пользователями, фильтрами и статистикой уведомлений
- Полная замена SQLite на MongoDB при наличии переменной окружения MONGO_URI
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError


def _iso_now() -> str:
    return datetime.now().isoformat()


class UserManager:
    """MongoDB реализация менеджера пользователей (API совместим с прежним)."""

    def __init__(self, mongo_uri: str = None, db_name: str = None):
        mongo_uri = mongo_uri or os.getenv("MONGO_URI")
        if not mongo_uri:
            raise RuntimeError("MONGO_URI не задан. Установите переменную окружения MONGO_URI.")
        db_name = db_name or os.getenv("MONGO_DB_NAME", "kleinanzeigen")

        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]

        # Коллекции
        self.col_users: Collection = self.db["users"]
        self.col_filters: Collection = self.db["user_filters"]
        self.col_stats: Collection = self.db["notification_stats"]
        self.col_groups: Collection = self.db["group_chats"]

        # Индексы
        self.col_users.create_index("user_id", unique=True)
        self.col_groups.create_index("chat_id", unique=True)
        self.col_filters.create_index("user_id", unique=True)
        self.col_stats.create_index([("recipient_id", ASCENDING), ("listing_id", ASCENDING)])
        self.col_stats.create_index([("recipient_id", ASCENDING), ("date_sent", ASCENDING)])
    
    def add_user(self, user_id: str, username: str = None, first_name: str = None, 
                 last_name: str = None, role: str = 'user', admin_id: str = None) -> bool:
        """Добавление/обновление пользователя со статусом 'pending'"""
        doc = {
            "user_id": str(user_id),
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "role": role or "user",
            "status": "pending",
            "date_added": _iso_now(),
            "added_by_admin": admin_id,
            # значения по умолчанию
            "max_notifications_per_day": 10,
        }
        try:
            self.col_users.update_one({"user_id": str(user_id)}, {"$setOnInsert": doc}, upsert=True)
            # Если пользователь уже был — не меняем статус на pending насильно
            return True
        except Exception as e:
            print(f"Ошибка добавления пользователя: {e}")
            return False
    
    def activate_user(self, user_id: str, subscription_days: int = 30) -> bool:
        """Активация пользователя и установка срока подписки."""
        try:
            expires_date = (datetime.now() + timedelta(days=subscription_days)).isoformat()
            res = self.col_users.update_one(
                {"user_id": str(user_id)},
                {"$set": {"status": "active", "date_activated": _iso_now(), "subscription_expires": expires_date}},
            )
            return res.modified_count > 0 or res.matched_count > 0
        except Exception as e:
            print(f"Ошибка активации пользователя: {e}")
            return False
    
    def deactivate_user(self, user_id: str, reason: str = None) -> bool:
        """Деактивация пользователя"""
        try:
            res = self.col_users.update_one(
                {"user_id": str(user_id)},
                {"$set": {"status": "inactive", "notes": reason, "date_deactivated": _iso_now()}},
            )
            return res.modified_count > 0 or res.matched_count > 0
        except Exception as e:
            print(f"Ошибка деактивации пользователя: {e}")
            return False
    
    def update_user_status(self, user_id: str, new_status: str, reason: str = None) -> bool:
        """Обновление статуса пользователя"""
        try:
            res = self.col_users.update_one({"user_id": str(user_id)}, {"$set": {"status": new_status, "notes": reason}})
            return res.modified_count > 0 or res.matched_count > 0
        except Exception as e:
            print(f"Ошибка обновления статуса пользователя: {e}")
            return False
    
    def reject_user(self, user_id: str, reason: str = None) -> bool:
        """Отклонение заявки пользователя (временно, может подать повторно)"""
        return self.update_user_status(user_id, 'rejected', reason)
    
    def ban_user(self, user_id: str, reason: str = None) -> bool:
        """Бан пользователя (постоянно, не может подать повторно)"""
        return self.update_user_status(user_id, 'banned', reason)
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Получение информации о пользователе"""
        try:
            user = self.col_users.find_one({"user_id": str(user_id)}, {"_id": 0})
            if not user:
                return None
            filters = self.col_filters.find_one({"user_id": str(user_id)}, {"_id": 0})
            if filters:
                user["filters"] = filters
            return user
        except Exception as e:
            print(f"Ошибка получения пользователя: {e}")
            return None
    
    def get_active_users(self) -> List[Dict]:
        """Получение всех активных пользователей"""
        try:
            now = _iso_now()
            cur = self.col_users.find({
                "status": "active",
                "$or": [
                    {"subscription_expires": {"$exists": False}},
                    {"subscription_expires": None},
                    {"subscription_expires": {"$gt": now}},
                ],
            }, {"_id": 0}).sort("date_added", -1)
            return list(cur)
        except Exception as e:
            print(f"Ошибка получения активных пользователей: {e}")
            return []
    
    def get_pending_users(self) -> List[Dict]:
        """Получение всех пользователей в статусе pending (ожидающих одобрения)"""
        try:
            cur = self.col_users.find({"status": "pending"}, {"_id": 0}).sort("date_added", -1)
            return list(cur)
        except Exception as e:
            print(f"Ошибка получения пользователей на рассмотрении: {e}")
            return []
    
    def get_active_group_chats(self) -> List[Dict]:
        """Получение всех активных групповых чатов"""
        try:
            cur = self.col_groups.find({"status": "active"}, {"_id": 0}).sort("date_added", -1)
            return list(cur)
        except Exception as e:
            print(f"Ошибка получения активных чатов: {e}")
            return []
    
    def can_receive_notification(self, user_id: str) -> bool:
        """Проверка может ли пользователь получать уведомления"""
        user = self.get_user(user_id)
        if not user:
            return False
        if user.get('status') != 'active':
            return False
        # Проверяем срок подписки
        expires = user.get('subscription_expires')
        if expires:
            try:
                if datetime.fromisoformat(expires) < datetime.now():
                    return False
            except Exception:
                pass
        # УБРАНО: Проверка лимита уведомлений в день - пользователь получает ВСЕ новые квартиры
        return True
    
    def log_notification(self, recipient_id: str, recipient_type: str, 
                        listing_id: str, listing_source: str):
        """Логирование отправленного уведомления"""
        try:
            self.col_stats.insert_one({
                "recipient_id": str(recipient_id),
                "recipient_type": recipient_type,
                "listing_id": str(listing_id),
                "date_sent": _iso_now(),
                "listing_source": listing_source,
            })
        except Exception as e:
            print(f"Ошибка логирования уведомления: {e}")
    
    def get_user_stats(self, user_id: str, days: int = 7) -> Dict:
        """Статистика пользователя за последние дни"""
        try:
            start_date = (datetime.now() - timedelta(days=days)).isoformat()
            total = self.col_stats.count_documents({"recipient_id": str(user_id), "date_sent": {"$gt": start_date}})
            agg = self.col_stats.aggregate([
                {"$match": {"recipient_id": str(user_id), "date_sent": {"$gt": start_date}}},
                {"$group": {"_id": "$listing_source", "count": {"$sum": 1}}},
            ])
            by_source = {doc["_id"]: doc["count"] for doc in agg}
            return {"total_notifications": total, "by_source": by_source, "period_days": days}
        except Exception as e:
            print(f"Ошибка получения статистики: {e}")
            return {}
    
    def set_user_filters(self, user_id: str, filters: Dict) -> bool:
        """Установка пользовательских фильтров"""
        try:
            doc = {
                "user_id": str(user_id),
                "min_price": filters.get("min_price"),
                "max_price": filters.get("max_price"),
                "min_rooms": filters.get("min_rooms"),
                "max_rooms": filters.get("max_rooms"),
                "min_area": filters.get("min_area"),
                "max_area": filters.get("max_area"),
                "excluded_keywords": filters.get("excluded_keywords", []),
                "preferred_locations": filters.get("preferred_locations", []),
                "search_urls": filters.get("search_urls", []),  # Новое поле
            }
            if doc["preferred_locations"] or doc["search_urls"]:
                now = datetime.now()
                doc["cities_assigned_date"] = now.isoformat()
                doc["subscription_expires"] = (now + timedelta(days=30)).isoformat()
            
            # Полная перезапись документа с заменой всех полей
            self.col_filters.replace_one(
                {"user_id": str(user_id)}, 
                doc, 
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Ошибка установки фильтров: {e}")
            return False
    
    def get_user_filters(self, user_id: str) -> Dict:
        """Получение пользовательских фильтров"""
        try:
            doc = self.col_filters.find_one({"user_id": str(user_id)}, {"_id": 0})
            return doc or {}
        except Exception as e:
            print(f"Ошибка получения фильтров: {e}")
            return {}
    
    def get_all_users_summary(self) -> Dict:
        """Сводка по всем пользователям для администратора"""
        try:
            total_users = self.col_users.count_documents({})
            active_users = self.col_users.count_documents({"status": "active"})
            pending_users = self.col_users.count_documents({"status": "pending"})
            active_chats = self.col_groups.count_documents({"status": "active"})
            today_str = datetime.now().date().isoformat()
            today_min = f"{today_str}T00:00:00"
            today_max = f"{today_str}T23:59:59"
            notifications_today = self.col_stats.count_documents({"date_sent": {"$gte": today_min, "$lte": today_max}})
            return {
                'total_users': total_users,
                'active_users': active_users,
                'pending_users': pending_users,
                'active_group_chats': active_chats,
                'notifications_sent_today': notifications_today
            }
        except Exception as e:
            print(f"Ошибка получения сводки: {e}")
            return {}
    
    def can_send_notification(self, user_id: str) -> bool:
        """Проверяет, может ли пользователь получить уведомление"""
        # Дублирующий метод (совместимость) — используйте can_receive_notification
        return self.can_receive_notification(user_id)
    
    def record_notification(self, recipient_id: str, recipient_type: str, listing_id: str, listing_source: str) -> bool:
        """Записывает факт отправки уведомления"""
        try:
            self.col_stats.insert_one({
                "recipient_id": str(recipient_id),
                "recipient_type": recipient_type,
                "listing_id": str(listing_id),
                "date_sent": _iso_now(),
                "listing_source": listing_source,
            })
            return True
        except Exception as e:
            print(f"Ошибка записи уведомления: {e}")
            return False
    
    def was_notification_sent(self, recipient_id: str, listing_id: str) -> bool:
        """Проверяет, была ли уже отправлена квартира этому получателю"""
        try:
            count = self.col_stats.count_documents({"recipient_id": str(recipient_id), "listing_id": str(listing_id)})
            return count > 0
        except Exception as e:
            print(f"Ошибка проверки уведомления: {e}")
            return False
    
    def get_notification_stats(self, user_id: str) -> Dict:
        """Получает статистику уведомлений пользователя"""
        try:
            today_str = datetime.now().date().isoformat()
            today_min = f"{today_str}T00:00:00"
            today_max = f"{today_str}T23:59:59"
            today_count = self.col_stats.count_documents({"recipient_id": str(user_id), "date_sent": {"$gte": today_min, "$lte": today_max}})
            total_count = self.col_stats.count_documents({"recipient_id": str(user_id)})
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            week_count = self.col_stats.count_documents({"recipient_id": str(user_id), "date_sent": {"$gte": week_ago}})
            return {"today": today_count, "this_week": week_count, "total": total_count}
        except Exception as e:
            print(f"Ошибка получения статистики уведомлений: {e}")
            return {'today': 0, 'this_week': 0, 'total': 0}
    
    def add_group_chat(self, chat_id: int, chat_title: str, added_by_admin: str, max_notifications: int = 20) -> bool:
        """Добавление группового чата"""
        try:
            self.col_groups.update_one(
                {"chat_id": str(chat_id)},
                {"$set": {
                    "chat_id": str(chat_id),
                    "chat_title": chat_title,
                    "chat_type": "group",
                    "status": "active",
                    "date_added": _iso_now(),
                    "max_notifications_per_day": max_notifications,
                    "added_by_admin": added_by_admin,
                }},
                upsert=True,
            )
            return True
        except Exception as e:
            print(f"Ошибка добавления группового чата: {e}")
            return False
    
    def get_active_group_chats(self) -> List[Dict]:
        """Получение активных групповых чатов"""
        try:
            cur = self.col_groups.find({"status": "active"}, {"_id": 0}).sort("date_added", -1)
            return list(cur)
        except Exception as e:
            print(f"Ошибка получения групповых чатов: {e}")
            return []
    
    def check_expired_subscriptions(self) -> List[str]:
        """Проверка истёкших подписок и отключение парсинга"""
        try:
            now = _iso_now()
            expired = list(self.col_filters.find({
                "subscription_expires": {"$ne": None, "$lt": now},
                "preferred_locations": {"$ne": []},
            }, {"_id": 0, "user_id": 1}))
            expired_user_ids = [doc["user_id"] for doc in expired]
            if expired_user_ids:
                self.col_filters.update_many(
                    {"user_id": {"$in": expired_user_ids}},
                    {"$set": {"preferred_locations": []}, "$unset": {"subscription_expires": ""}},
                )
            return expired_user_ids
        except Exception as e:
            print(f"Ошибка проверки подписок: {e}")
            return []
    
    def get_users_expiring_soon(self, days: int = 3) -> List[Dict]:
        """Получение пользователей с истекающими подписками"""
        try:
            warning_date = (datetime.now() + timedelta(days=days)).isoformat()
            cur = self.col_filters.find({
                "subscription_expires": {"$ne": None, "$lt": warning_date, "$gt": _iso_now()},
                "preferred_locations": {"$ne": []},
            }, {"_id": 0, "user_id": 1, "subscription_expires": 1})
            users = []
            for doc in cur:
                u = self.col_users.find_one({"user_id": doc["user_id"]}, {"_id": 0, "username": 1, "first_name": 1})
                users.append({
                    "user_id": doc["user_id"],
                    "username": (u or {}).get("username"),
                    "first_name": (u or {}).get("first_name"),
                    "expires": doc.get("subscription_expires"),
                })
            return users
        except Exception as e:
            print(f"Ошибка получения истекающих подписок: {e}")
            return []

    def get_all_users(self) -> List[Dict]:
        """Возвращает всех пользователей с ключевыми полями."""
        try:
            cur = self.col_users.find({}, {"_id": 0}).sort("date_added", -1)
            return list(cur)
        except Exception as e:
            print(f"Ошибка получения списка пользователей: {e}")
            return []

    def delete_user(self, user_id: str) -> bool:
        """Полностью удаляет пользователя и связанные данные (фильтры, статистику)."""
        try:
            self.col_filters.delete_many({"user_id": str(user_id)})
            self.col_stats.delete_many({"recipient_id": str(user_id)})
            res = self.col_users.delete_one({"user_id": str(user_id)})
            return res.deleted_count > 0
        except Exception as e:
            print(f"Ошибка удаления пользователя: {e}")
            return False

    # Дополнительно: подсчёт уведомлений с момента времени (для парсера)
    def count_notifications_since(self, user_id: str, since_iso: str) -> int:
        try:
            return self.col_stats.count_documents({"recipient_id": str(user_id), "date_sent": {"$gt": since_iso}})
        except Exception:
            return 0
    
    def get_users_by_search_url(self, url: str) -> List[Dict]:
        """Получить всех пользователей, подписанных на конкретный URL"""
        try:
            # Находим все фильтры где search_urls содержит этот URL
            filters = list(self.col_filters.find({"search_urls": url}))
            
            if not filters:
                return []
            
            # Получаем информацию о пользователях
            user_ids = [f['user_id'] for f in filters]
            users = list(self.col_users.find({
                "user_id": {"$in": user_ids},
                "status": "active"
            }))
            
            # Объединяем данные
            result = []
            for user in users:
                user_filter = next((f for f in filters if f['user_id'] == user['user_id']), {})
                result.append({
                    **user,
                    'filters': user_filter
                })
            
            return result
        except Exception as e:
            print(f"Ошибка получения пользователей по URL: {e}")
            return []
    
    def get_all_search_urls(self) -> List[str]:
        """Получить все уникальные search_urls от всех пользователей"""
        try:
            # Агрегация для извлечения всех уникальных URLs
            pipeline = [
                {"$match": {"search_urls": {"$exists": True, "$ne": []}}},
                {"$unwind": "$search_urls"},
                {"$group": {"_id": "$search_urls"}}
            ]
            
            result = list(self.col_filters.aggregate(pipeline))
            urls = [item['_id'] for item in result]
            
            return urls
        except Exception as e:
            print(f"Ошибка получения всех URLs: {e}")
            return []

