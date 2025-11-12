import argparse
import os
from pymongo import MongoClient


def connect_db():
    # Prefer miniapp-specific var if present, then common names
    uri = (
        os.getenv("MINIAPP_MONGODB_URI")
        or os.getenv("MONGODB_URI")
        or os.getenv("MONGO_URI")
        or "mongodb://localhost:27017"
    )
    db_name = os.getenv("MONGO_DB_NAME", "kleinanzeigen")
    client = MongoClient(uri)
    return client[db_name]


def clear_collections(db, targets):
    total = 0
    for col in targets:
        if col in db.list_collection_names():
            res = db[col].delete_many({})
            print(f"{col}: deleted {res.deleted_count}")
            total += res.deleted_count
        else:
            print(f"{col}: collection does not exist, skipped")
    return total


def main():
    parser = argparse.ArgumentParser(description="Clear MongoDB collections for miniapp/main parser")
    parser.add_argument("--yes", action="store_true", help="Do not prompt for confirmation")
    parser.add_argument(
        "--only",
        nargs="*",
        help="Specific collections to clear (default: users user_filters listings notification_stats group_chats)",
    )

    args = parser.parse_args()

    default_cols = [
        "users",
        "user_filters",
        "listings",
        "notification_stats",
        "group_chats",
    ]
    targets = args.only if args.only else default_cols

    if not args.yes:
        print("WARNING: This will delete ALL documents from collections:")
        print(", ".join(targets))
        confirm = input("Type 'yes' to proceed: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return

    db = connect_db()
    total = clear_collections(db, targets)
    print(f"Done. Total deleted: {total}")


if __name__ == "__main__":
    main()
