import argparse
from miniapp.user_manager import UserManager


def main():
    ap = argparse.ArgumentParser(description="Patch user's Immowelt search URL to a provided full URL")
    ap.add_argument("user_id")
    ap.add_argument("immowelt_url")
    args = ap.parse_args()

    uid = str(args.user_id)
    new_url = args.immowelt_url.strip()
    um = UserManager()
    f = um.get_user_filters(uid) or {"search_urls": [], "preferred_locations": []}
    urls = f.get("search_urls", [])
    # Rebuild clean list: keep exactly one kleinanzeigen (if exists) and one immowelt (new)
    cleaned = []
    seen_klein = False
    for u in urls:
        if isinstance(u, str) and "kleinanzeigen.de" in u and not seen_klein:
            cleaned.append(u)
            seen_klein = True
    cleaned.append(new_url)
    um.set_user_links(uid, cleaned, f.get("preferred_locations", []))
    print("Updated search_urls:")
    for u in cleaned:
        print("-", u)


if __name__ == "__main__":
    main()
