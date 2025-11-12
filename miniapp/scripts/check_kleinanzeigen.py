import argparse
from typing import List
from miniapp.parsers.kleinanzeigen import KleinanzeigenParser
from miniapp.user_manager import UserManager


def load_urls_for_user(user_id: str) -> List[str]:
    um = UserManager()
    f = um.get_user_filters(user_id) or {}
    urls = f.get("search_urls", [])
    return [u for u in urls if "kleinanzeigen.de" in u]


def main():
    parser = argparse.ArgumentParser(description="Check Kleinanzeigen parser output")
    parser.add_argument("--user", help="User ID to take URLs from DB", default=None)
    parser.add_argument("urls", nargs="*", help="Explicit URLs to parse (overrides --user)")
    args = parser.parse_args()

    urls: List[str] = []
    if args.urls:
        urls = args.urls
    elif args.user:
        urls = load_urls_for_user(args.user)
    else:
        print("Provide --user <id> or explicit URLs")
        return

    kp = KleinanzeigenParser()
    for u in urls:
        print("\nURL:", u)
        try:
            listings = kp.parse(u)
        except Exception as e:
            print("Error:", e)
            continue
        print("count:", len(listings))
        for x in listings[:10]:
            title = (x.title or "").replace("\n", " ")
            print("-", title[:100], "|", x.location, "|", f"{x.price}€", "|", x.url)


if __name__ == "__main__":
    main()
