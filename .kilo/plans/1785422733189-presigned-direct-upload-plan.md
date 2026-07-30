# Presigned Direct Upload — план

## Контекст

TakeFlow должен принимать медиа до 2-3 часов (10-30 ГБ). Текущая реализация
(до изменений) проксировала байты через процесс API: `media.py` читал
`UploadFile` чанками по 1 MiB и писал на локальный диск. Проблемы:

- API-воркер занят на всё время загрузки
- при переходе на S3 трафик удваивается (клиент → API → S3)
- `StoragePort.save_stream` возвращал `tuple[Path, int]` — у объекта в S3 нет
  `Path`, то есть «swap провайдера = смена env» не работал
- `FileTooLargeError` срабатывал после приёма лишних байт
- обрыв на 4 ГБ = загрузка с нуля
- `content_type` брался из заголовка клиента; `python-magic` в зависимостях был,
  но не использовался
- роутер импортировал `LocalStorage` напрямую — протечка адаптера в API-слой

## Решение

Presigned multipart с порогом: файлы < 32 MiB одним PUT, больше — multipart с
параллельными частями и retry по отдельной части. Байты идут клиент → storage,
API только выдаёт тикеты и верифицирует результат.

Локальный адаптер тоже реализует presign (HMAC-подписанный URL на собственный
sink-эндпоинт), чтобы dev-путь совпадал с прод-путём.

---

## СТАТУС: реализовано без плана (нужно ревью)

Все изменения в рабочем дереве, **коммитов нет**. `git status` — 17 изменённых,
8 новых файлов. Проверено: `uv run pytest` → 47 passed, `uv run ruff check .` →
All checks passed.

### Домен
- [x] `src/domain/enums.py` — `UploadStatus` (initiated/completed/aborted/expired), `UploadMode` (single/multipart)
- [x] `src/domain/entities.py` — `UploadSession`, `StoredObject`, `UploadTicket`, `PartUploadTicket`; в `Media` заменён `path` → `storage_key`, добавлен `checksum`
- [x] `src/domain/errors.py` — `UploadSessionNotFoundError`, `UploadNotFinishedError`, `UploadSizeMismatchError`, `UploadStateError`, `StorageError`
- [x] `src/domain/upload_policy.py` (новый) — вся политика: `validate_extension`, `validate_declared_size`, `sniff_matches_extension`, `plan_upload`, `build_storage_key`. Вынесена из адаптера, т.к. «что принимаем» — бизнес-правило
- [x] `src/domain/ports/services.py` — `StoragePort` переписан на объектную семантику: `presign_put`, `create_multipart`, `presign_parts`, `complete_multipart`, `abort_multipart`, `stat`, `open_range`, `materialize`, `save_stream`, `delete`
- [x] `src/domain/ports/repositories.py` — `UploadSessionRepository`

### Инфраструктура
- [x] `src/infrastructure/storage/s3.py` (новый) — aioboto3, presigned multipart, path-style для MinIO, `materialize` скачивает во временный файл
- [x] `src/infrastructure/storage/local.py` (перезаписан) — HMAC-presign, части как `.part-NNNNN`, защита от path traversal через `is_relative_to`
- [x] `src/infrastructure/models.py` — `UploadSessionModel`, `media.storage_key` (unique), `media.checksum`
- [x] `src/infrastructure/repositories/upload_session.py` (новый) — `fetch_stale` с `FOR UPDATE SKIP LOCKED`
- [x] `src/infrastructure/repositories/media.py` — маппинг под `storage_key`
- [x] `alembic/versions/0002_direct_uploads.py` (новый) — `path` → `storage_key` с переносом данных, таблица `upload_sessions`, партиальный индекс по `status='initiated'`

### Приложение
- [x] `src/application/services/upload_service.py` (новый) — `init`/`complete`/`abort`/`reap_stale`. `complete` идемпотентен, размер берётся из `storage.stat` (не от клиента), magic bytes проверяются
- [x] `src/application/services/media_service.py` — убран `upload`, осталось чтение

### API
- [x] `src/api/routers/uploads.py` (новый) — `POST /uploads`, `POST /uploads/{id}/complete`, `DELETE /uploads/{id}`, плюс `PUT /uploads/sink/{key}` для локального адаптера (`include_in_schema=False`)
- [x] `src/api/schemas/uploads.py` (новый)
- [x] `src/api/routers/media.py` — убран импорт `LocalStorage`, убран проксирующий upload, `transcribe` теперь через `storage.materialize` в `TemporaryDirectory`
- [x] `src/api/deps.py`, `src/api/main.py` — регистрация

### Настройки
- [x] `StorageSettings` — `presign_ttl_seconds`, `presign_secret`, `local_public_url`, `session_reap_after_seconds`
- [x] `CoreSettings.max_upload_bytes` — 2 GiB → 32 GiB

### Тесты (новые, 47 штук)
- [x] `tests/conftest.py`, `tests/test_upload_policy.py`, `tests/test_local_storage.py`, `tests/test_upload_service.py`
- [x] `pyproject.toml` — `pythonpath = ["."]`, `asyncio_default_fixture_loop_scope`

### Незакрытое
- [ ] `uploads.py` — исправление 204-эндпоинта (`response_class=Response`) внесено, но **импорт `Response` из fastapi не добавлен**; `from src.api.main import app` сейчас падает
- [ ] `reap_stale` нигде не вызывается — нужен планировщик в воркере
- [ ] `docs/PORTFOLIO_ROADMAP.md` дублирует README — решить, удалять ли

---

## Задачи для реализации

1. **Починить импорт `Response`** в `src/api/routers/uploads.py`, затем
   проверить `uv run python -c "from src.api.main import app"` — сейчас это
   единственная известная поломка.
2. **Ревью `aioboto3`**: зависимость добавлена без согласования, потянула 19
   транзитивных пакетов. Либо подтвердить, либо `uv remove aioboto3` и выбрать
   другой клиент.
3. **Вызов `reap_stale`** из `src/worker/` по расписанию — без него multipart-части
   висят в бакете и тарифицируются.
4. **Интеграционный тест на роутер** через `httpx.AsyncClient` + `LocalStorage`:
   полный цикл init → PUT в sink → complete. Сейчас покрыты только слои по
   отдельности.
5. **MinIO в `docker-compose.yml`** — чтобы S3-путь проверялся локально, а не
   только в проде.
6. **`.env.example`** — новые переменные (`STORAGE_PRESIGN_SECRET`,
   `STORAGE_LOCAL_PUBLIC_URL`, `STORAGE_PRESIGN_TTL_SECONDS`).
7. **README** — обновить блок API под новый флоу загрузки.

## Валидация

```bash
cd backend
uv run ruff check . && uv run pytest
uv run python -c "from src.api.main import app; print(len(app.routes))"
```

Миграция: `uv run alembic upgrade head`, затем `downgrade -1` и снова `upgrade`
— проверить, что перенос `path` → `storage_key` обратим.

## Риски

- **`presign_secret` имеет дефолт** `dev-only-insecure-presign-secret`. Если
  локальный адаптер окажется доступен извне с этим дефолтом — любой сможет
  писать в хранилище. Нужен явный запрет старта с дефолтом при
  `STORAGE_PROVIDER=local` вне debug.
- **Аутентификации нет вообще** — ни на `/uploads`, ни на `/media`. Любой может
  инициировать загрузку и прочитать чужой транскрипт по `file_id`. Отдельная
  задача, но блокирующая для публичного деплоя.
- **Rate limit отсутствует** — `/uploads` позволяет забить хранилище.
- **Миграция 0002 меняет `media.path`** на `storage_key`. На пустой БД
  безопасно; на данных — перенос есть, но старые значения были абсолютными
  локальными путями, а не ключами объектов.
- **ETag локального адаптера** (`{part:05d}-{size}`) — не S3-совместимый
  формат. Клиенту всё равно (он просто эхом возвращает), но тесты, завязанные на
  формат, будут разными для local и s3.

## Открытые вопросы

1. **Окружение разработки.** Сейчас всё поставлено в `backend/.venv` на Windows
   (проверено: `sys.prefix` = `backend\.venv`, глобальный Python не тронут).
   Оставляем venv на Windows, или переходим на WSL / только Docker? Влияет на
   ffmpeg, faster-whisper и CUDA. Рекомендация: Docker как основной путь,
   venv только для тестов и линта.
2. **Экономия токенов.** Правила в `.kilo/rules/main.md` при написании кода на
   моё поведение не повлияли — было ~15 полных чтений файлов. Плюс `rg` в
   правилах указан, но в системе не установлен. Рекомендация: добавить в
   `kilo.json` блок `permissions` с запретом на `.venv/`, `__pycache__/`,
   `uv.lock`, и убрать `rg` из rules либо поставить его.
3. **Порог multipart** — сейчас 32 MiB, часть 16 MiB. Оставляем?
