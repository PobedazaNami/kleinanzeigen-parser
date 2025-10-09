# AI Agent Instructions for Kleinanzeigen-Parser

## 🚫 CRITICAL RULE #1: NO DOCUMENTATION FILES

**NEVER create additional documentation or instruction files in this project.**

Forbidden file patterns:
- `SETUP.md`, `GUIDE.md`, `INSTRUCTIONS.md`, `TUTORIAL.md`, `DEPLOYMENT.md`
- `PROJECT_STATUS.md`, `REFACTORING.md`, `INTEGRATION.md`, `API.md`
- `QUICKSTART.md`, `READY_TO_USE.md`, `RESULT.md`
- `test_*.py` files (tests are deleted, not maintained)
- `*_old.py` backup files

**Only `README.md` contains documentation. Update it, don't create new files.**

## Architecture Overview

This is a **tri-parser system** for German apartment rental listings:
- **KleinanzeigenParser** (`kleinanzeigen_parser.py`) - parses Kleinanzeigen.de (formerly eBay Kleinanzeigen)
- **ImmoweltParser** (`immowelt_parser.py`) - parses Immowelt.de with **Firecrawl API** to bypass bot detection
- **ImmobilienScout24Parser** (`immobilienscout_parser.py`) - parses ImmobilienScout24.de with **Firecrawl API** to bypass authentication

All parsers inherit from **BaseParser** (`base_parser.py`) for shared functionality. They run **independently** and **in parallel** via `main.py`.

### Key Design Decisions

1. **Parser Independence**: Each parser is self-contained. Refactored from ImmoweltParser inheriting from KleinanzeigenParser to both inheriting from BaseParser.

2. **"Neu" Filter**: ImmoweltParser and ImmobilienScout24Parser only process listings with `data-testid="cardmfe-tag-testid-new"` badge or text "Neu" - no date checking needed.

3. **Firecrawl Integration**: Immowelt and ImmobilienScout24 return 403/401 without Firecrawl API. Falls back to regular HTTP if unavailable (will fail with 403/401).

## Core Components

```
base_parser.py                      # Common parsing logic, DB, Telegram notifications
kleinanzeigen_parser.py             # Kleinanzeigen-specific selectors & logic
immowelt_parser.py                  # Immowelt-specific selectors + Firecrawl
immobilienscout_parser.py           # ImmobilienScout24-specific selectors + Firecrawl
db_manager.py                       # SQLite database operations
main.py                             # Production runner with multi-site orchestration
```

## Critical Workflows

### Running the Parser

```bash
# Production mode (continuous, 30-min intervals)
python main.py

# Single run (one cycle, then exit)
python main.py --single-run

# With Firecrawl API (required for Immowelt)
export FIRECRAWL_API_KEY='fc-your-key'
python main.py
```

### Configuration Setup

1. Copy `config.example.json` → `config.json`
2. Copy `.env.example` → `.env`
3. Set `FIRECRAWL_API_KEY` in `.env` (get from https://firecrawl.dev)
4. Set Telegram tokens in `.env` or `config.json`

### URL Detection Logic

`main.py` auto-detects parser type from URL domain:
- `kleinanzeigen.de` → KleinanzeigenParser
- `immowelt.de` → ImmoweltParser
- `immobilienscout24.de` → ImmobilienScout24Parser

URLs are grouped by type, separate config files created (`config_kleinanzeigen_temp.json`, `config_immowelt_temp.json`, `config_scout_temp.json`).

## Project-Specific Patterns

### Immowelt Selectors (CSS classes may change)

```python
# Location: span.css-wpv6zq
# Price: span.css-9wpf20  
# "Neu" badge: span[data-testid="cardmfe-tag-testid-new"]
```

These are **brittle**. If Immowelt changes HTML, update these selectors.

### Price Parsing (German Format)

German uses `.` for thousands, `,` for decimals:
- `753.71 €` = 753 euros, 71 cents → parse as `753`
- `1.234,56 €` = 1234 euros, 56 cents → parse as `1234`

Logic in `immowelt_parser.py` lines 352-374.

### Date Handling Differences

- **Kleinanzeigen**: Parses dates from listing page (`extract_listing_date`)
- **Immowelt**: **NO DATE PARSING** - filters by "Neu" badge only, uses `datetime.now()`
- **ImmobilienScout24**: **NO DATE PARSING** - filters by "Neu" badge only, uses `datetime.now()`

### Firecrawl API Usage

```python
# In immowelt_parser.py and immobilienscout_parser.py
result = self.firecrawl.scrape(
    url,
    formats=['html'],
    only_main_content=False,
    wait_for=2000  # Wait for JS to load
)
```

**Rate limit**: 500 requests/month free tier. `max_listings_immowelt: 2` and `max_listings_immobilienscout24: 2` in config limits consumption.

## Integration Points

### Telegram Notifications

All parsers send to same Telegram chat via `base_parser.py`:
- New listings: `send_telegram_notification(listing_data)`
- Errors: `send_error_notification(error_msg, error_type)`

### Database Schema

SQLite (`data/listings.db`):
```sql
CREATE TABLE listings (
    id TEXT PRIMARY KEY,
    title TEXT,
    price INTEGER,
    size INTEGER,
    rooms TEXT,
    location TEXT,
    description TEXT,
    url TEXT UNIQUE,
    date_posted TEXT,
    date_found TEXT,
    hash TEXT,
    parser_source TEXT  -- 'kleinanzeigen', 'immowelt' or 'immobilienscout24'
)
```

Hash prevents duplicates: `md5(title + price + size + location)`.

## External Dependencies

- **BeautifulSoup4**: HTML parsing
- **firecrawl-py**: Immowelt scraping (requires API key)
- **python-telegram-bot**: Notifications
- **requests**: HTTP requests
- **sqlite3**: Built-in, no install needed

## Common Mistakes to Avoid

1. **Don't create test files** - they will be deleted
2. **Don't remove Firecrawl fallback** - parser should log warning, not crash
3. **Don't make Kleinanzeigen depend on Immowelt/Scout24** - they must be independent
4. **Don't hardcode dates for Immowelt/Scout24** - use "Neu" badge filter only
5. **Don't create instruction files** - update README.md instead

## Debugging Tips

Logs in `logs/parser.log` and `logs/errors.log` (rotating, 10MB/5MB limits).

To test Immowelt without Firecrawl:
```python
# Set use_firecrawl=False temporarily to see 403 errors
self.use_firecrawl = False
```

Check HTML selectors if parsing fails:
```python
soup = parser.get_page(url)
print(soup.prettify())  # Inspect actual HTML structure
```
