# 🚀 Деплой на сервер

## Быстрый старт

```bash
# 1. Подключаемся к серверу
ssh root@49.13.219.223

# 2. Клонируем проект
cd /opt
git clone https://github.com/PobedazaNami/kleinanzeigen-parser.git
cd kleinanzeigen-parser

# 3. Создаём .env файл с настройками
cp .env.example .env
nano .env
```

### Настройка .env

Заполните следующие обязательные параметры:

```bash
TELEGRAM_BOT_TOKEN=ваш_токен_бота
TELEGRAM_CHAT_ID=ваш_chat_id
FIRECRAWL_API_KEY=fc-f7ae42a185794709ac96f1a35974a468
```

### Настройка config.json

```bash
cp config.example.json config.json
nano config.json
```

Убедитесь что в `search_urls` есть URL для всех 3 сайтов:
- Kleinanzeigen.de
- Immowelt.de
- ImmobilienScout24.de

## Запуск через Docker (рекомендуется)

```bash
# Сборка и запуск
docker-compose up -d

# Проверка логов
docker-compose logs -f

# Остановка
docker-compose down

# Перезапуск
docker-compose restart
```

## Запуск напрямую (без Docker)

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск миграции базы данных
python migrate_db.py

# Одноразовый запуск (тест)
python main.py --single-run

# Непрерывный режим (каждые 30 минут)
python main.py
```

## Автозапуск через systemd

Создайте файл `/etc/systemd/system/kleinanzeigen-parser.service`:

```ini
[Unit]
Description=Kleinanzeigen Multi-Site Parser
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/kleinanzeigen-parser
ExecStart=/usr/bin/python3 /opt/kleinanzeigen-parser/main.py
Restart=always
RestartSec=60
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Активация:

```bash
systemctl daemon-reload
systemctl enable kleinanzeigen-parser
systemctl start kleinanzeigen-parser
systemctl status kleinanzeigen-parser
```

## Мониторинг

```bash
# Логи (если Docker)
docker-compose logs -f

# Логи (если systemd)
journalctl -u kleinanzeigen-parser -f

# Файловые логи
tail -f logs/parser.log
tail -f logs/errors.log
tail -f logs/kleinanzeigen_parser.log
tail -f logs/immowelt_parser.log
tail -f logs/immobilienscout24_parser.log

# Статистика базы данных
sqlite3 data/listings.db "SELECT COUNT(*), parser_source FROM listings GROUP BY parser_source"
```

## Обновление

```bash
cd /opt/kleinanzeigen-parser

# Останавливаем парсер
docker-compose down  # или systemctl stop kleinanzeigen-parser

# Обновляем код
git pull

# Запускаем миграцию базы данных
python migrate_db.py

# Пересобираем и запускаем
docker-compose build --no-cache
docker-compose up -d

# или для systemd
systemctl start kleinanzeigen-parser
```

## Проверка работоспособности

После запуска проверьте:

1. **Telegram** - должно прийти сообщение "Multi-Site Parser запущен"
2. **Логи** - парсеры инициализированы с Firecrawl ✅
3. **База данных** - новые квартиры сохраняются

```bash
# Проверка парсеров
docker-compose logs | grep "Firecrawl: ✅"

# Должно быть 3 строки:
# Kleinanzeigen.de (без Firecrawl)
# Immowelt.de (Firecrawl: ✅)
# ImmobilienScout24.de (Firecrawl: ✅)
```

## Troubleshooting

### Проблема: "Firecrawl: ❌"

Проверьте:
```bash
grep FIRECRAWL_API_KEY .env
```

Должно быть: `FIRECRAWL_API_KEY=fc-f7ae42a185794709ac96f1a35974a468`

### Проблема: Квартиры не приходят в Telegram

```bash
# Очистите базу для теста
sqlite3 data/listings.db "DELETE FROM listings"

# Запустите одноразовый тест
python main.py --single-run

# Новые квартиры должны прийти в Telegram
```

### Проблема: "Invalid header value"

Это проблема только GitHub Actions. На сервере не будет!

## Параметры запуска

```bash
# Одноразовый запуск (один цикл парсинга)
python main.py --single-run

# Непрерывный режим (каждые 30 минут, по умолчанию)
python main.py

# Изменить интервал через config.json
{
  "settings": {
    "check_interval_minutes": 15  // каждые 15 минут
  }
}
```

## Резервное копирование

```bash
# Бэкап базы данных
cp data/listings.db data/listings.db.backup_$(date +%Y%m%d)

# Бэкап конфигурации
tar -czf config_backup_$(date +%Y%m%d).tar.gz config.json .env
```

## Важно! 🔒

- Файл `.env` содержит секретные токены - **НЕ коммитьте в git!**
- База данных в `data/listings.db` - Docker volume сохраняется между перезапусками
- Логи ротируются автоматически (10MB для parser.log, 5MB для errors.log)
