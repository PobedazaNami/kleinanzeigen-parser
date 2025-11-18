from datetime import datetime
import pytz
from typing import List, Dict, Any, Optional
from .db import get_db
from .config import SUBSCRIPTION_DURATION, TRIAL_DURATION, USER_DAILY_LIMIT, NOTIFY_INTERVAL_MINUTES
from datetime import timedelta

class UserManager:
    def __init__(self):
        self.db = get_db()

    # Users
    def upsert_user(self, user_id: str, username: str = "", first_name: str = "", last_name: str = ""):
        self.db.users.update_one(
            {"user_id": user_id},
            {"$setOnInsert": {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "role": "user",
                "status": "pending",
                "subscription_expires": None,
                "max_notifications_per_day": USER_DAILY_LIMIT,
                "date_added": datetime.utcnow().isoformat(),
                "date_activated": None,
                "notes": ""
            }},
            upsert=True
        )

    def approve_user(self, user_id: str):
        """Mark user as approved by admin but DO NOT start subscription period.
        Subscription will be started explicitly via mark_paid().
        """
        now_iso = datetime.utcnow().isoformat()
        self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "status": "active",
                "approved_at": now_iso,
                # Keep subscription_expires/date_activated unchanged until payment
            }, "$setOnInsert": {
                "date_added": now_iso,
                "role": "user",
                "max_notifications_per_day": USER_DAILY_LIMIT,
            }}
        )

    def mark_trial(self, user_id: str):
        """Start a free trial period for the user for TRIAL_DURATION (14 days).
        Sets date_activated to now and subscription_expires to now + 14 days.
        """
        now = datetime.utcnow()
        self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "status": "active",
                "date_activated": now.isoformat(),
                "subscription_expires": (now + TRIAL_DURATION).isoformat(),
                "awaiting_payment": False,
            }, "$unset": {
                "requested_subscription": ""
            }}
        )

    def mark_paid(self, user_id: str):
        """Start a paid subscription window for the user for SUBSCRIPTION_DURATION.
        Also sets date_activated to now.
        """
        now = datetime.utcnow()
        self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "status": "active",
                "date_activated": now.isoformat(),
                "subscription_expires": (now + SUBSCRIPTION_DURATION).isoformat(),
                "awaiting_payment": False,
            }}
        )

    def delete_user(self, user_id: str) -> bool:
        """Hard-delete user and related data. Returns True if deleted.
        Protects admin accounts from deletion.
        """
        u = self.db.users.find_one({"user_id": user_id})
        if not u:
            return False
        if u.get("role") == "admin":
            # do not delete admins
            return False
        self.db.user_filters.delete_one({"user_id": user_id})
        self.db.notification_stats.delete_many({"recipient_id": user_id})
        res = self.db.users.delete_one({"user_id": user_id})
        return res.deleted_count > 0

    def get_active_users(self) -> List[Dict[str, Any]]:
        now_iso = datetime.utcnow().isoformat()
        return list(self.db.users.find({
            "status": "active",
            "$or": [
                {"subscription_expires": None},
                {"subscription_expires": {"$gte": now_iso}}
            ]
        }))

    def get_all_users_for_broadcast(self) -> List[Dict[str, Any]]:
        """Return all users (active, pending, inactive) for admin broadcast.
        Excludes banned users and returns user_id, username, status.
        """
        return list(self.db.users.find(
            {"status": {"$ne": "banned"}},
            {"user_id": 1, "username": 1, "first_name": 1, "status": 1}
        ))

    def can_send_notification(self, user_id: str) -> bool:
        # count notifications today
        today = datetime.utcnow().date().isoformat()
        count = self.db.notification_stats.count_documents({
            "recipient_id": user_id,
            "date": today,
            "notification_type": "new_listing"
        })
        user = self.db.users.find_one({"user_id": user_id})
        limit = user.get("max_notifications_per_day", USER_DAILY_LIMIT) if user else USER_DAILY_LIMIT
        return count < limit

    # Filters
    def set_user_links(self, user_id: str, search_urls: List[str], preferred_locations: Optional[List[str]] = None, access_mode: Optional[str] = None):
        """Assign links and optional access mode.
        access_mode:
            - "trial": start a 14-day trial window (only once, do not extend on reassign)
            - "subscription": keep trial fields cleared and rely on users.subscription_expires
            - None: just update links without changing access mode
        Note: Does not extend subscription on reassign to comply with business rule.
        """
        preferred_locations = preferred_locations or []
        now = datetime.utcnow()
        now_iso = now.isoformat()

        set_fields: Dict[str, Any] = {
            "user_id": user_id,
            "search_urls": search_urls,
            "preferred_locations": preferred_locations,
            "cities_assigned_date": now_iso,
            # next_run_at будет выставлен при первом фактическом запуске (run_for_user)
            "next_run_at": None,
            "last_run_at": None,
        }

        if access_mode in ("trial", "subscription"):
            set_fields["access_mode"] = access_mode

        # Prepare on-insert defaults
        on_insert = {"subscription_expires": None}

        # Read current filter doc to decide trial logic
        f = self.db.user_filters.find_one({"user_id": user_id}) or {}

        if access_mode == "trial":
            # Start trial only once; do not re-extend on reassignment
            if not f.get("trial_started_at"):
                set_fields["trial_started_at"] = now_iso
                from datetime import timedelta as _td
                # 14-day trial window
                set_fields["trial_expires_at"] = (now + _td(days=14)).isoformat()
        elif access_mode == "subscription":
            # Clear trial markers when moving to subscription mode, but DO NOT modify
            # users.subscription_expires or date_activated here. Subscription start
            # must be controlled explicitly by admin approval (approve_user).
            set_fields["trial_started_at"] = None
            set_fields["trial_expires_at"] = None

        self.db.user_filters.update_one(
            {"user_id": user_id},
            {"$set": set_fields, "$setOnInsert": on_insert},
            upsert=True,
        )

    def get_user_filters(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.db.user_filters.find_one({"user_id": user_id})

    def mark_user_run(self, user_id: str):
        now_utc = datetime.utcnow()
        # Align to the nearest Berlin local :00/:30, then store as UTC
        berlin = pytz.timezone('Europe/Berlin')
        now_berlin = datetime.now(berlin)
        remainder = now_berlin.minute % NOTIFY_INTERVAL_MINUTES
        add_min = (NOTIFY_INTERVAL_MINUTES - remainder) if remainder != 0 else NOTIFY_INTERVAL_MINUTES
        next_berlin = now_berlin.replace(second=0, microsecond=0) + timedelta(minutes=add_min)
        next_dt = next_berlin.astimezone(pytz.utc)
        self.db.user_filters.update_one(
            {"user_id": user_id},
            {"$set": {
                "last_run_at": now_utc.isoformat(),
                "next_run_at": next_dt.isoformat(),
            }}
        )

    def has_access(self, user_doc: Dict[str, Any], user_filters: Optional[Dict[str, Any]]) -> bool:
        """Return True if user is allowed to receive listings now.
        Logic:
          - If filters.access_mode == 'trial': allow only until trial_expires_at
          - Else (subscription/default): allow only if users.subscription_expires is in the future
        """
        user_filters = user_filters or {}
        mode = user_filters.get("access_mode")
        if mode == "trial":
            te = user_filters.get("trial_expires_at")
            if not te:
                return False
            try:
                from datetime import datetime as _dt
                return _dt.utcnow() <= _dt.fromisoformat(te)
            except Exception:
                return False
        # subscription/default
        sub = (user_doc or {}).get("subscription_expires")
        if not sub:
            return False
        try:
            from datetime import datetime as _dt
            return _dt.utcnow() <= _dt.fromisoformat(sub)
        except Exception:
            return False

    # Listings / notifications
    def record_listing(self, listing: Dict[str, Any]) -> Optional[str]:
        # Ensure single listing per hash
        try:
            self.db.listings.insert_one(listing)
            return listing.get("listing_id") or listing.get("hash")
        except Exception:
            return None

    def record_notification(self, recipient_id: str, listing_id: str, notification_type: str):
        self.db.notification_stats.update_one(
            {"recipient_id": recipient_id, "listing_id": listing_id},
            {"$set": {
                "recipient_id": recipient_id,
                "listing_id": listing_id,
                "notification_type": notification_type,
                "date": datetime.utcnow().date().isoformat(),
                "ts": datetime.utcnow().isoformat()
            }}, upsert=True
        )
