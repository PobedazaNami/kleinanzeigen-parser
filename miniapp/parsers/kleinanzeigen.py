from typing import List
from bs4 import BeautifulSoup
from .base import BaseParser, Listing
from datetime import datetime

class KleinanzeigenParser(BaseParser):
    source = "kleinanzeigen"

    def parse(self, url: str) -> List[Listing]:
        soup = self.get(url)
        cards = soup.select("article.aditem")
        out: List[Listing] = []
        for c in cards:
            # Filter by Heute only (classes vary; search in bottom row text)
            # Use full card text to detect 'Heute' as markup varies
            full_text = c.get_text(" ", strip=True).lower()
            import re
            has_time = re.search(r"\b\d{1,2}:\d{2}\b", full_text) is not None
            if ("heute" not in full_text) and (not has_time):
                continue
            # Card text used by multiple parsers below
            card_text = c.get_text(" ", strip=True)
            # Prefer the title anchor under h2 with class 'ellipsis'
            title_el = (
                c.select_one("h2 a.ellipsis")
                or c.select_one("a.ellipsis")
                or c.select_one('h2 a[href*="/s-anzeige/"]')
                or c.find('a', href=True)
            )
            if not title_el:
                continue
            title = title_el.get("title") or title_el.get_text(strip=True)
            link = title_el.get("href") or ""
            if link and link.startswith("/"):
                link = f"https://www.kleinanzeigen.de{link}"
            price_el = (
                c.select_one(".aditem-main--middle--price-shipping .aditem-main--middle--price")
                or c.select_one(".aditem-main--middle--price")
                or c.select_one(".aditem-details--top--price")
                or c.select_one(".aditem-main--top--price")
            )
            price = 0
            price_text = price_el.get_text(strip=True) if price_el else ""
            if price_text:
                digits = ''.join(ch for ch in price_text if ch.isdigit())
                if digits:
                    try:
                        price = int(digits)
                    except Exception:
                        price = 0
            if price == 0:
                # Fallback: scan full card text for number with Euro sign
                import re as _re
                m = _re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)\s*€", card_text)
                if m:
                    try:
                        price = int(m.group(1).replace('.', ''))
                    except Exception:
                        price = 0
            loc_el = c.select_one(".aditem-main--top--left")
            location = loc_el.get_text(strip=True) if loc_el else ""
            # Try to parse size (m²) and rooms from card text
            import re as _re
            size_val = None
            m2 = _re.search(r"(\d+(?:[.,]\d+)?)\s*m²", card_text)
            if m2:
                try:
                    size_val = int(float(m2.group(1).replace(',', '.')))
                except Exception:
                    size_val = None
            rooms_val = None
            rz = _re.search(r"(\d+(?:[.,]\d+)?)\s*(?:zi|zimmer)\b", card_text, flags=_re.IGNORECASE)
            if rz:
                rooms_val = rz.group(1).replace(',', '.')
            lid = c.get("data-adid") or link
            h = self.hash_listing(title, price, location)
            out.append(Listing(
                listing_id=lid,
                title=title,
                price=price,
                location=location,
                url=link,
                date_found=datetime.utcnow().isoformat(),
                parser_source=self.source,
                hash=h,
                size=size_val,
                rooms=rooms_val,
            ))
        return out
