# AI-ассистент студента — лабораторная № 1

Telegram-бот на Python 3.12 и aiogram: локальная модель Qwen через Ollama,
история и настройки каждого пользователя в PostgreSQL. Обрабатывает текст в личных чатах.

## Запуск на macOS с Docker

Нужны запущенные Docker Desktop и Ollama. Если модель уже скачана, повторный `pull` не нужен.

```bash
ollama pull qwen2.5:1.5b
cp .env.example .env  # Только при первой настройке: существующий .env не заменять.
```

В `.env` задайте `BOT_TOKEN` от BotFather и `POSTGRES_PASSWORD`.
Для уже созданной базы сохраните существующий пароль. Настройки модели:

```dotenv
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:1.5b
LLM_TIMEOUT=120
LLM_MAX_TOKENS=700
HISTORY_MAX_MESSAGES=12
CONTEXT_MAX_CHARS=12000
```

`ollama` — техническое значение ключа, локальный сервер его игнорирует.
Настройки внешнего провайдера указываются в тех же переменных.

```bash
docker compose --profile cloud up -d --build
docker compose --profile cloud ps
docker compose exec -T bot python -m app.healthcheck
```

Профиль `cloud` здесь включает сервис `bot`; приведённые команды запускают его локально.
Не запускайте второй polling-процесс с тем же токеном. После изменения кода повторите
команду с `--build`. Данные базы хранятся в volume и переживают пересоздание бота.

## Команды

| Команда | Действие |
|---|---|
| `/start` | Возможности и список команд |
| `/study` | Объяснение программирования; режим по умолчанию |
| `/translate` | Перевод на язык, указанный в сообщении; есть few-shot-примеры |
| `/quiz` | Три вопроса по учебной теме и ключ ответов |
| `/settings` | Текущий режим, модель, temperature |
| `/settings 0.7` | Установить 0.0, 0.3, 0.7 или 1.0 |
| `/reset` | Очистить свою историю, сохранив режим и temperature |

Переключение режима очищает историю. Команды не передаются модели.
Во время генерации показывается «печатает». Ошибки и неполные ответы не сохраняются;
длинные ответы отправляются частями без разметки.

## Проверки и материалы сдачи

```bash
.venv/bin/python -m pytest -m 'not integration' -q
RUN_INTEGRATION=1 .venv/bin/python -m pytest -m integration -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Интеграционные тесты создают и удаляют отдельные тестовые контейнеры и volumes;
рабочую базу не используют. Подготовка `.venv` описана в справке шаблона.

- [Архитектура, ограничения и демонстрация](docs/lab1-run.md).
- [Отчёт и результаты эксперимента](docs/lab1-report.md).
- [12 ответов через Telegram](docs/lab1-experiment.json) и [таблица](docs/lab1-experiment.csv).
- [Предварительные API-запуски с токенами](docs/lab1-api-experiment.json).
- [Справка исходного шаблона: локальный Python, облако, скрипты](docs/template-readme.md).

Повторить программный эксперимент на работающем контейнере:

```bash
mkdir -p outputs
docker compose exec -T bot python - --output - < scripts/experiment.py > outputs/lab1-experiment.json
```

Скрипт получает 12 реальных ответов и сравнивает неполную и улучшенную инструкции.
Для каждого запроса обработчик `/reset` вызывается программно с временным user_id.
Скрипт не отправляет сообщения в Telegram. Отдельный эксперимент из 12 запусков
через Telegram уже выполнен студентом; результаты находятся в `docs/lab1-experiment.json`.
Протокол повторного проведения описан в `docs/lab1-run.md`.
