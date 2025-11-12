import argparse
import sys
from bs4 import BeautifulSoup
from miniapp.parsers.base import BaseParser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    args = ap.parse_args()
    bp = BaseParser()
    soup = bp.get(args.url)
    html = soup.prettify()
    print("HTML length:", len(html))
    cards = soup.select("article.aditem")
    print("cards:", len(cards))
    for i, c in enumerate(cards[:3]):
        t = c.get_text(" ", strip=True)
        print(f"-- card {i} text sample:", t[:300])


if __name__ == "__main__":
    main()
