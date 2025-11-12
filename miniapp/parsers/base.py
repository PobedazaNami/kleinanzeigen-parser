import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from ..config import DEFAULT_HEADERS

@dataclass
class Listing:
    listing_id: str
    title: str
    price: int
    location: str
    url: str
    date_found: str
    parser_source: str
    hash: str
    # optional enriched fields (parsed from list card only)
    size: int | None = None
    rooms: str | None = None

class BaseParser:
    source = "base"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def get(self, url: str) -> BeautifulSoup:
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")

    def hash_listing(self, title: str, price: int, location: str) -> str:
        base = f"{title}|{price}|{location}|{self.source}"
        return hashlib.md5(base.encode("utf-8")).hexdigest()

    def parse(self, url: str) -> List[Listing]:
        raise NotImplementedError
