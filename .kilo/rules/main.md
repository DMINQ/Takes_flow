# TakeFlow
Stack: Python 3.12, FastAPI, SQLAlchemy 2.0 async, psycopg3, Alembic, FastStream/Redis, faster-whisper, ffmpeg-python, pedalboard, uv

## Команды
- тесты: `uv run pytest` (или `uv run --group tests pytest`)
- линт: `uv run ruff check . && uv run black --check .` (или `--group lint`)
- запуск: `docker compose up --build` или `uv run uvicorn src.api.main:app --reload`
- ВАЖНО: перед коммитом — `uv run ruff check . && uv run pytest`

## Bash-инструменты
- поиск контента: `rg`
- поиск файлов: `fd`
- структура: запускай `tree` сам, не спрашивай
- JSON: `jq`

## Архитектура
- Hexagonal: `api`/`worker` → `application` → `domain`; `infrastructure` реализует порты
- Порты в `src/domain/ports/`, адаптеры в `src/infrastructure/`
- Не читай файлы целиком — ищи нужную функцию через `rg`

## Конвенции
- line-length: 110 (ruff)
- Async везде: SQLAlchemy async sessions, async FastAPI deps
- Новые адаптеры — только в `infrastructure/`, реализуют интерфейс из `domain/ports/`

## Нельзя
- Не трогать `uv.lock` вручную — только через `uv add/remove`
- Не добавлять бизнес-логику в `api/` или `infrastructure/`
- Не читать `.venv/` или `__pycache__/`

## Токены
- .venv/__pycache__/node_modules физически недоступны через permissions в kilo.json — не пытайся их читать
- /clear между несвязанными задачами — это на пользователе, не забывай напоминать
