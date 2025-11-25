from typing import List
from bs4 import BeautifulSoup
from .base import BaseParser, Listing
from datetime import datetime
import os
try:
    from firecrawl import FirecrawlApp  # type: ignore
except Exception:
    FirecrawlApp = None
from ..config import FIRECRAWL_API_KEY, IMMOWELT_USE_FIRECRAWL
from urllib.parse import urlsplit, urlunsplit

def _normalize_expose_url(link: str) -> str:
    if not link:
        return link
    parts = urlsplit(link)
    # strip query and fragment for stable ID
    return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))

class ImmoweltParser(BaseParser):
    source = "immowelt"

    def __init__(self):
        super().__init__()
        self._firecrawl = None
        if IMMOWELT_USE_FIRECRAWL and FIRECRAWL_API_KEY and FirecrawlApp is not None:
            try:
                self._firecrawl = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
            except Exception:
                self._firecrawl = None

    def _get_html(self, url: str) -> BeautifulSoup:
        # First try firecrawl if enabled
        if self._firecrawl is not None and 'immowelt.de' in url:
            # Use rawHtml format for full HTML
            try:
                result = self._firecrawl.scrape(
                    url,
                    formats=['rawHtml'],
                    only_main_content=False,
                    wait_for=5000,
                )
                # New SDK returns Document object with raw_html attribute
                html = getattr(result, 'raw_html', None) or getattr(result, 'html', '')
                # Accept any non-empty HTML; downstream parsing will decide
                if html:
                    return BeautifulSoup(html, 'html.parser')
            except Exception as e:
                # Log but continue to fallback
                pass
            # If firecrawl fails, return empty soup (avoid direct HTTP 403)
            return BeautifulSoup("", 'html.parser')
        # Fallback to normal request (only if firecrawl is not available)
        return self.get(url)

    def parse(self, url: str) -> List[Listing]:
        soup = self._get_html(url)
        out: List[Listing] = []
        processed = set()
        
        # Strategy: Find all "Neu" badges, then find nearest /expose/ link for each
        import re
        neu_elements = soup.find_all(string=lambda x: x and x.strip() == 'Neu')
        
        for neu_el in neu_elements:
            # Go up to find container with /expose/ link
            container = neu_el.parent if neu_el else None
            found_link = None
            
            for _ in range(15):  # search up to 15 levels
                if not container:
                    break
                    
                # Look for /expose/ link in this container
                link_el = container.find('a', href=re.compile(r'/expose/\d+'))
                if link_el:
                    found_link = link_el
                    # Now go back down to find smallest container with both Neu and link
                    # Use the current container as data source
                    break
                    
                container = container.parent
            
            if not found_link:
                continue
                
            href = found_link.get('href', '')
            if not href or '/expose/' not in href:
                continue
                
            # Normalize URL
            if href.startswith('/'):
                full_url = f"https://www.immowelt.de{href}"
            else:
                full_url = href
            norm_url = _normalize_expose_url(full_url)
            
            if norm_url in processed:
                continue
            processed.add(norm_url)
            
            # Extract data from a narrow container around the link (not the huge parent)
            # Go up only 2-3 levels from link to get individual card data
            card_container = found_link
            for _ in range(3):  # just 3 levels up from link
                if card_container:
                    card_container = card_container.parent
            
            if not card_container:
                continue
                
            # Get text from this narrow card container
            text = card_container.get_text(' ', strip=True)
            
            # Extract title
            title = found_link.get_text(strip=True) or found_link.get('title', '')
            if not title or len(title) < 3:
                title = "Wohnung zur Miete"
            
            # Parse price - look for "XXX € Kaltmiete" pattern first (most reliable)
            price = 0
            # Pattern 1: "1.540 € Kaltmiete" or "1540 € Kaltmiete"
            price_match = re.search(r'([\d.]+)\s*€\s*Kaltmiete', text, re.IGNORECASE)
            if price_match:
                price_str = price_match.group(1).replace('.', '').replace(',', '.')
                try:
                    price = int(float(price_str))
                except:
                    pass
            
            # Pattern 2 (fallback): find all prices and take the first reasonable one
            if not price or price < 100:
                all_prices = re.findall(r'(\d{3,}(?:\.\d{3})*(?:,\d+)?)\s*€', text)
                for p_str in all_prices:
                    try:
                        p_val = int(float(p_str.replace('.', '').replace(',', '.')))
                        if 200 <= p_val <= 10000:  # reasonable rent range
                            price = p_val
                            break
                    except:
                        continue
            
            # Parse size
            size_val = None
            m2_match = re.search(r'(\d+(?:[.,]\d+)?)\s*m²', text)
            if m2_match:
                try:
                    size_val = int(float(m2_match.group(1).replace(',', '.')))
                except:
                    pass
            
            # Parse rooms
            rooms_val = None
            rooms_match = re.search(r'(\d+(?:[.,]\d+)?)\s*Zimmer', text, flags=re.IGNORECASE)
            if rooms_match:
                rooms_val = rooms_match.group(1).replace(',', '.')
            
            # Parse location (postal code + city)
            location = ''
            loc_match = re.search(r'(\d{5}\s+[A-Za-zÄÖÜäöüß\s\-]+)', text)
            if loc_match:
                location = loc_match.group(1).strip()[:100]
            
            out.append(Listing(
                listing_id=norm_url or full_url,
                title=title[:200],
                price=price,
                location=location,
                url=norm_url or full_url,
                date_found=datetime.utcnow().isoformat(),
                parser_source=self.source,
                hash=self.hash_listing(title, price, location),
                size=size_val,
                rooms=rooms_val,
            ))
        
        return out
