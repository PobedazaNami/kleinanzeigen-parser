# Настройка GitHub Actions для автоматического парсинга

## Как это работает:

GitHub Actions будет автоматически запускать парсер каждые 30 минут:
- Запускается в 14:00 → работает 3-5 минут → выключается
- Запускается в 14:30 → работает 3-5 минут → выключается  
- И так далее 24/7

## Настройка секретов:

1. Идите в ваш GitHub репозиторий
2. Settings → Secrets and variables → Actions
3. Нажмите "New repository secret"
4. Добавьте два секрета:

### TELEGRAM_BOT_TOKEN
- Name: `TELEGRAM_BOT_TOKEN`
- Secret: `ваш_токен_бота_здесь`

### TELEGRAM_CHAT_ID  
- Name: `TELEGRAM_CHAT_ID`
- Secret: `ваш_chat_id_здесь`

## Активация workflow:

1. Закоммитьте изменения:
```bash
git add .
git commit -m "Add GitHub Actions workflow for automated parsing"
git push
```

2. Workflow активируется автоматически и начнет работать каждые 30 минут

## Проверка работы:

1. Actions → Kleinanzeigen Parser
2. Посмотрите логи выполнения
3. Проверьте сообщения в Telegram

## Управление:

- **Остановить**: Settings → Actions → Disable actions
- **Изменить расписание**: Отредактируйте `.github/workflows/parser.yml`
- **Запустить вручную**: Actions → Kleinanzeigen Parser → Run workflow

## Лимиты:

- **Бесплатно**: 2000 минут в месяц  
- **Один запуск**: ~3-5 минут
- **В месяц**: ~400-600 минут использования
- **Достаточно для**: 48 запусков в день

## Troubleshooting:

Если не работает:
1. Проверьте секреты в Settings → Secrets  
2. Посмотрите логи в Actions
3. Убедитесь, что токен Telegram правильный