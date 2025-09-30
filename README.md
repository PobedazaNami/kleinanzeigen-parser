# Kleinanzeigen Parser 🏠

[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.8%2B-green?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue?logo=telegram)](https://telegram.org/)

Автоматический парсер объявлений о сдаче квартир с Kleinanzeigen.de с уведомлениями в Telegram.

## ✨ Особенности

- 🐳 **Docker развертывание** - запуск одной командой
- ⏰ **Автоматический парсинг** каждые 30 минут  
- 🔍 **Умная фильтрация** (исключение WG, только сегодняшние объявления)
- 📱 **Telegram уведомления** о новых объявлениях и ошибках
- 🗄️ **SQLite база данных** для отслеживания объявлений
- 📝 **Полное логирование** всех операций
- 🛡️ **Защита от блокировок** (случайные задержки, ротация User-Agent)

## 🚀 Быстрый запуск

### Требования
- Docker и Docker Compose
- Telegram бот (получить у @BotFather)

### 1. Клонирование проекта

```bash
# Клонировать репозиторий
git clone https://github.com/YOUR_USERNAME/kleinanzeigen-parser.git
cd kleinanzeigen-parser
```

### 2. Настройка секретов

**Вариант A: Environment файл (рекомендуемый)**
```bash
# Создайте .env файл из примера
cp .env.example .env

# Отредактируйте .env с вашими секретами
TELEGRAM_BOT_TOKEN=your_real_bot_token_here
TELEGRAM_CHAT_ID=your_real_chat_id_here
```

**Вариант B: Конфигурационный файл**
```bash
# Отредактируйте config.json
{
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN_HERE", 
    "chat_id": "YOUR_CHAT_ID_HERE"
  }
}
```

> 💡 **Рекомендация**: Используйте .env файл для секретов, config.json для остальных настроек

### 3. Запуск

```bash
# Сборка и запуск
docker-compose up -d

# Просмотр логов
docker-compose logs -f
```

### 4. Управление

```bash
# Остановка
docker-compose down

# Перезапуск
docker-compose restart

# Обновление
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 📊 Мониторинг

```bash
# Статус контейнера
docker-compose ps

# Логи в реальном времени
docker-compose logs -f

# Статистика использования ресурсов
docker stats kleinanzeigen_parser
```

## 🔧 Структура проекта

```
kleinanzeigen-parser/
├── kleinanzeigen_parser.py    # Основной парсер
├── main.py                    # Точка входа
├── config.json                # Конфигурация 
├── docker-compose.yml         # Docker Compose
├── Dockerfile                 # Docker образ
└── requirements.txt           # Python зависимости
```

## ⚙️ Конфигурация

Основные настройки в `config.json`:

```json
{
  "telegram": {
    "bot_token": "токен_бота",
    "chat_id": "id_чата"
  },
  "search_urls": [
    "URL_для_поиска_квартир"
  ],
  "filters": {
    "exclude_titles": ["WG", "wg", "Wg"],
    "min_price": 300,
    "max_price": 2000
  },
  "settings": {
    "check_interval_minutes": 30,
    "random_delay_min": 3,
    "random_delay_max": 8
  },
  "date_filtering": {
    "only_today": true
  }
}
```

## 🐛 Устранение проблем

### Контейнер не запускается
```bash
docker-compose build
docker-compose logs
```

### Telegram не работает  
1. Проверьте токен бота
2. Убедитесь, что бот добавлен в чат
3. Проверьте chat_id

### Парсер не находит объявления
1. Проверьте URLs в конфигурации
2. Посмотрите логи на предмет блокировок

## � Для разработчиков

### Локальная разработка без Docker

```bash
# Клонировать и перейти в папку
git clone https://github.com/YOUR_USERNAME/kleinanzeigen-parser.git
cd kleinanzeigen-parser

# Создать виртуальное окружение
python -m venv venv

# Активировать (Windows)
venv\Scripts\activate
# Или (Linux/Mac)
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Скопировать и настроить конфигурацию
cp config.example.json config.json
# Отредактировать config.json

# Запустить
python main.py
```

### Структура проекта

```
kleinanzeigen-parser/
├── kleinanzeigen_parser.py    # Основная логика парсера
├── main.py                    # Точка входа приложения
├── db_manager.py              # Управление базой данных
├── config.example.json        # Пример конфигурации
├── requirements.txt           # Python зависимости
├── Dockerfile                 # Docker образ
├── docker-compose.yml         # Docker Compose конфигурация
└── docs/                      # Документация
    ├── DEPLOYMENT.md          # Инструкции по развертыванию
    └── API.md                 # API документация (если есть)
```

## �📋 Полная документация

Подробные инструкции смотрите в [DEPLOYMENT.md](DEPLOYMENT.md)

## 🤝 Участие в проекте

1. Сделайте Fork проекта
2. Создайте ветку для новой функции (`git checkout -b feature/AmazingFeature`)
3. Зафиксируйте изменения (`git commit -m 'Add some AmazingFeature'`)
4. Отправьте в ветку (`git push origin feature/AmazingFeature`)
5. Откройте Pull Request

## 📄 Лицензия

Распространяется под лицензией MIT. Смотрите [LICENSE](LICENSE) для получения дополнительной информации.

---

**💡 Совет**: Для получения chat_id отправьте сообщение боту и перейдите по ссылке:
`https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`