from miniapp.parsers.base import BaseParser
from bs4 import BeautifulSoup

url = 'https://www.kleinanzeigen.de/s-wohnung-mieten/koblenz/c203l5419'

bp = BaseParser()
soup = bp.get(url)
cards = soup.select('article.aditem')
print('cards', len(cards))
heute = 0
for i, c in enumerate(cards):
    t = (c.select_one('.aditem-main--bottom') or c).get_text(' ', strip=True).lower()
    if 'heute' in t:
        heute += 1
        if heute <= 3:
            print('sample heute card', i)
            print(t[:200])
print('heute', heute)
