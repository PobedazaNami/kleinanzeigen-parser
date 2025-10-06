# Changelog - Добавление поддержки Immowelt.de

## Что изменилось

### Новые файлы
- **`immowelt_parser.py`** - Новый парсер для сайта Immowelt.de
  - Наследуется от `KleinanzeigenParser`
  - Использует те же фильтры и базу данных
  - Специфические CSS селекторы для Immowelt.de

### Измененные файлы

#### `main.py`
- Добавлен импорт `ImmoweltParser`
- Добавлен импорт `urlparse` для определения типа сайта
- Добавлены методы:
  - `detect_site_type(url)` - определяет тип сайта по URL
  - `group_urls_by_site(urls)` - группирует URL по типам сайтов
- Изменена логика запуска:
  - Теперь поддерживается несколько парсеров одновременно
  - Каждый парсер получает свои URL из конфигурации
  - Парсеры работают последовательно в одном цикле

#### `config.example.json`
- Добавлен пример URL для Immowelt.de в массив `search_urls`

#### `README.md`
- Обновлено название: "Multi-Site Apartment Parser"
- Добавлена информация о поддержке Immowelt.de
- Добавлен раздел "Поддерживаемые сайты"
- Добавлены примеры URL для обоих сайтов
- Обновлена структура проекта
- Добавлена инструкция по получению URL для Immowelt.de

## Как использовать

### 1. Обновите конфигурацию

Добавьте URL для Immowelt.de в `config.json`:

```json
{
  "search_urls": [
    "https://www.kleinanzeigen.de/s-wohnung-mieten/darmstadt/wohnung/k0c203l4888",
    "https://www.immowelt.de/liste/darmstadt/wohnungen/mieten?d=true&sd=DESC&sf=TIMESTAMP&sp=1"
  ]
}
```

### 2. Запустите парсер

```bash
# С Docker
docker-compose restart

# Или без Docker
python main.py
```

## Технические детали

### Архитектура
- **Наследование**: `ImmoweltParser` наследует от `KleinanzeigenParser`
- **Общая база данных**: Оба парсера используют одну SQLite базу данных
- **Общие фильтры**: Фильтры применяются ко всем сайтам
- **Уникальные ID**: Объявления из Immowelt имеют префикс `immowelt_`

### CSS Селекторы для Immowelt.de

#### Список объявлений
- `div[data-test="result-list-item"] a[href*="/expose/"]`
- `a[href*="/expose/"]`
- `article a[href*="/expose/"]`

#### Страница объявления
- Заголовок: `h1[data-test="expose-title"]`
- Цена: `div[data-test="price"] strong`
- Характеристики: `div[data-test="hardfact"]`
- Адрес: `div[data-test="address"]`
- Описание: `div[data-test="description-text"]`

### Извлечение даты
Immowelt может использовать:
- Точные даты: `DD.MM.YYYY`
- Относительные даты: "heute", "gestern", "vor X Tagen"

## Преимущества

✅ Один конфиг для всех сайтов  
✅ Одна база данных  
✅ Одни фильтры  
✅ Единые уведомления в Telegram  
✅ Легко добавлять новые сайты  

## Будущие улучшения

- [ ] Добавить поддержку ImmoScout24.de
- [ ] Добавить поддержку WG-Gesucht.de
- [ ] Параллельный парсинг сайтов
- [ ] Индивидуальные фильтры для каждого сайта
