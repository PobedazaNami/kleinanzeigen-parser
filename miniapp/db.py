from pymongo import MongoClient, ASCENDING
from pymongo.errors import OperationFailure
from .config import MONGODB_URI, MONGODB_DB

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGODB_URI)
        _db = _client[MONGODB_DB]
        try:
            ensure_indexes(_db)
        except Exception:
            # Non-fatal: continue without enforcing indexes
            pass
    return _db


def _ensure_unique_index(coll, keys, name: str):
    info = coll.index_information()
    if name in info:
        # If already unique, nothing to do; if not unique, drop and recreate
        if info[name].get("unique"):
            return
        try:
            coll.drop_index(name)
        except Exception:
            pass
    try:
        coll.create_index(keys, name=name, unique=True)
    except OperationFailure:
        # Likely due to duplicate data; keep going without raising to allow app startup
        # Non-unique index fallback (with explicit name to avoid conflicts)
        try:
            coll.create_index(keys, name=f"{name}_nonuniq")
        except Exception:
            pass
    except Exception:
        pass


def ensure_indexes(db):
    try:
        _ensure_unique_index(db.users, [("user_id", ASCENDING)], name="user_id_1")
    except Exception:
        pass
    try:
        _ensure_unique_index(db.user_filters, [("user_id", ASCENDING)], name="user_filters_user_id_1")
    except Exception:
        pass
    try:
        _ensure_unique_index(db.listings, [("hash", ASCENDING)], name="hash_1")
    except Exception:
        pass
    # Compound unique for recipient+listing notifications
    try:
        db.notification_stats.create_index([
            ("recipient_id", ASCENDING), ("listing_id", ASCENDING)
        ], name="recipient_listing_unique", unique=True)
    except Exception:
        try:
            db.notification_stats.create_index([
                ("recipient_id", ASCENDING), ("listing_id", ASCENDING)
            ], name="recipient_listing_nonuniq")
        except Exception:
            pass
