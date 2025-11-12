import argparse
from miniapp.user_manager import UserManager


def main():
    ap = argparse.ArgumentParser(description="Clear per-user notification stats")
    ap.add_argument("user_id")
    args = ap.parse_args()
    um = UserManager()
    res = um.db.notification_stats.delete_many({"recipient_id": str(args.user_id)})
    print(f"Deleted notifications: {res.deleted_count}")


if __name__ == "__main__":
    main()
