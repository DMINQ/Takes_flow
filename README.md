# TakeFlow

AI-assisted voiceover / dialogue editor. Загружаете запись — получаете готовый файл
без тишины, оговорок и неудачных дублей. То, что вручную занимает час в Audition,
занимает минуту.

> **Status:** Step 1 (scaffold) complete — hexagonal architecture, uv, multi-stage
> Docker, async Postgres + Alembic, transactional outbox → FastStream/Redis,
> upload + word-level transcription через порты/адаптеры.

<!-- TODO: GIF таймлайна — красный/жёлтый/зелёный + плейбек со скипом вырезанного -->

## Показатели

Заполняются по мере готовности слоёв — числа честные или отсутствуют.

| Метрика | Значение |
|---|---|
| Стоимость обработки на минуту аудио | TBD |
| F1 детекции неудачных дублей | TBD |
| Доля фрагментов, дошедших до LLM | TBD (цель < 10%) |
| p95 latency обработки 10-мин записи | TBD |
| Cache hit rate semantic cache | TBD (цель > 40%) |

---

## Архитектура

Hexagonal (ports & adapters). Зависимости внутрь: `api`/`worker`/`cli` →
`application` → `domain`; `infrastructure` реализует порты домена. Смена внешней
зависимости (local↔remote Whisper, fs↔S3, stub↔pyannote, LLM on↔off) — это
**изменение env**, а не кода.

```
backend/
├── pyproject.toml / uv.lock       # deps через uv (canonical)
├── deploy/Dockerfile              # multi-stage: uv builder → slim runtime
├── deploy/entrypoint.sh           # alembic upgrade head → exec CMD
├── alembic/                       # async migrations
└── src/
    ├── domain/                    # чистое ядро, без внешних зависимостей
    │   ├── entities.py            # Media, Job, Word, Phrase, TimelineRegion, Speaker
    │   ├── enums.py               # JobStatus, RegionKind(keep/auto_cut/review), ...
    │   ├── dto.py                 # PipelineContext — проходит через каждый плагин
    │   ├── errors.py
    │   └── ports/                 # Transcriber, Diarizer, Storage, AudioEngine,
    │                              #   LLM, *Repository
    ├── application/               # use-cases, pipeline, detectors, agents
    ├── infrastructure/            # адаптеры портов
    │   ├── db.py                  # async engine/session, Base
    │   ├── models.py              # ORM (media/jobs/timeline_regions/outbox)
    │   ├── transcribers/local.py  # faster-whisper
    │   ├── diarizers/stub.py      # single-speaker → pyannote позже
    │   ├── storage/local.py       # filesystem → S3/MinIO позже
    │   └── audio/engine.py        # ffmpeg + pedalboard
    ├── api/                       # FastAPI: main, deps, routers/, schemas/
    ├── worker/                    # python -m src.worker.main / .relay
    ├── cli/                       # takeflow trim — тот же application-слой
    └── settings/                  # config.py + providers.py (выбор адаптеров)
```

Четыре представления «одной сущности» держатся раздельно намеренно:
**domain entities** (бизнес) · **PipelineContext** (DTO пайплайна) ·
**api/schemas** (HTTP-контракт) · **infrastructure/models** (ORM).

### Три интерфейса, одно ядро

- **REST** — загрузка, таймлайн, экспорт
- **WebSocket/SSE** — прогресс обработки в реальном времени (юзер ждёт минуты и
  должен видеть, что происходит)
- **CLI** — `takeflow trim input.wav -o out.wav`, ноль дублирования логики

CLI существует не для галочки: это проверка, что гексагональная архитектура
настоящая. Если бы логика протекла в роутеры, CLI бы не собрался.

### Асинхронность: transactional outbox → broker → worker

1. **API** пишет `Media` + `Job` + `OutboxEvent` в одной транзакции, отдаёт `job_id`
2. **relay** (`src.worker.relay`) публикует pending-события в брокер
3. **worker** (`src.worker.main`) читает, забирает job (`SELECT … FOR UPDATE`), гоняет пайплайн

Outbox, а не прямой publish — потому что запись в БД и отправка в брокер иначе не
атомарны: упавший publish оставит job, который никто не обработает.

FastStream поверх **Redis** (тот же decorator API, что у RabbitMQ, но легче).
`BROKER_PROVIDER=nats` меняет транспорт без правок кода.

### Chunked processing: fan-out / fan-in

Час аудио не обрабатывается за один запрос. Файл режется на чанки по границам
тишины, чанки обрабатываются параллельно несколькими воркерами, результат
собирается с учётом границ слов.

```
upload → split(chunks) ─┬→ worker#1 ─┐
                        ├→ worker#2 ─┼→ merge → timeline
                        └→ worker#N ─┘
```

Отсюда честно вырастают: идемпотентность на уровне чанка, частичные отказы,
порядок сборки, прогресс как отношение готовых чанков к общему числу.

---

## AI-каскад: дорогое только когда дешёвое не справилось

Три уровня детекции по возрастанию стоимости. Уровень включается, только если
предыдущий не уверен.

| Уровень | Инструмент | Что ловит | Стоимость |
|---|---|---|---|
| 1. DSP | энергия, питч, пауза (pedalboard) | тишина, ~70% случаев | ~0 |
| 2. Statistical | fuzzy + embeddings | повторы, дубли дублей | низкая |
| 3. LLM | LLM + RAG | смысловые ошибки, спорные места | высокая |

Router направляет фрагмент дальше только при низкой уверенности предыдущего
уровня. Это режет стоимость на порядок и даёт измеримое «LLM вызывается на N%
фрагментов». Здесь же — причина, по которой нужны semantic cache и метрики
стоимости: без каскада они были бы косметикой.

Отдельно: **prosody-детектор не использует LLM вообще**. Энергия и питч считаются
DSP. Там, где LLM не нужен, его нет.

### Мультиагентный слой — там, где есть арбитраж

Четыре сигнала считаются независимо и **конфликтуют между собой**, поэтому нужен
граф с арбитром, а не последовательная цепочка:

```
transcript
   ├→ FillerAgent      (эмм/ааа — regex + LLM)
   ├→ RepeatAgent      (дубли фраз — fuzzy + embeddings)
   ├→ ProsodyAgent     (энергия/питч — DSP, без LLM)
   └→ SemanticAgent    (смысловые ошибки — LLM + RAG)
        ↓
   ArbiterAgent → timeline + confidence
```

Низкий confidence → регион помечается `review`, а не вырезается. Автоматика не
удаляет то, в чём не уверена.

### RAG: потому что «плохой дубль» контекстно-зависим

Что считать оговоркой, зависит от того, как звучат *хорошие* дубли этого диктора.
Generic-промпт этого не знает.

- Транскрипты прошлых сессий индексируются в pgvector: манера речи, типичные
  оговорки, глоссарий терминов проекта
- При детекции — retrieve похожих фрагментов → few-shot в промпт
- Качество мерится: precision@k на размеченном наборе, до/после

### Feedback loop: правки юзера как бесплатная разметка

Юзер вернул регион из `auto_cut` в `keep` — это метка ошибки детектора. Правки
пишутся как обучающий сигнал и питают golden dataset и few-shot примеры.
Петля замкнута: чем больше пользуются, тем точнее детекция.

---

## Data layer

- **S3/MinIO** через существующий `StoragePort` — аудио и артефакты (тяжёлым
  бинарям не место в БД)
- **Медальон-слои**: bronze (raw upload) → silver (транскрипт + фичи, Parquet) →
  gold (агрегаты качества)
- **Nightly DAG** (Airflow/Prefect): пересчёт метрик, drift-детекция по WER,
  сравнение моделей
- **Model A/B**: `TRANSCRIBER_MODEL` уже переключается через env — остаётся
  логировать качество по модели и сравнивать

---

## Надёжность

- **Idempotency**: `idempotency_key` на job — повторная загрузка не пересчитывает
- **Circuit breaker + exponential backoff** на LLM/ASR адаптерах
- **Dead-letter queue** для упавших job + ручной replay
- **Graceful degradation**: LLM недоступен → fallback на уровни 1-2 каскада,
  продукт продолжает работать
- **OpenTelemetry**: единый trace_id через api → outbox → relay → worker → LLM
- Structured logging

---

## Evaluation

- Golden dataset: размеченные вручную записи (пополняется из feedback loop)
- `uv run pytest tests/eval` → precision / recall / F1 по детекции
- LLM-as-judge для семантических кейсов
- **CI-гейт**: F1 упал больше чем на 5% → PR красный

Без eval остальные слои недоказуемы, поэтому он идёт раньше AI-фич.

---

## Quick start (Docker)

```bash
docker compose up --build
#   API docs:  http://localhost:8000/docs
#   services:  api, worker, relay, db (postgres), redis
```

Миграции применяются при старте контейнера `api`. Модель Whisper скачивается один
раз в volume `takeflow-models` (общий для api и worker).

Загрузка — client-direct: API выдаёт presigned-тикет, байты идут клиент → storage
напрямую (в dev — через локальный HMAC-signed sink того же процесса), затем клиент
подтверждает завершение. Ни один байт не проходит через API-воркер.

```bash
# 1. init — declare filename/size, get a presigned ticket (single or multipart)
INIT=$(curl -s -X POST http://localhost:8000/api/v1/uploads \
  -H "Content-Type: application/json" \
  -d '{"filename":"sample.wav","size_bytes":'"$(stat -c%s sample.wav)"',"content_type":"audio/wav"}')
SESSION_ID=$(echo "$INIT" | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
PUT_URL=$(echo "$INIT" | python -c "import sys,json;print(json.load(sys.stdin)['single']['url'])")

# 2. client PUTs the bytes straight to storage (the presigned URL)
curl -s -X PUT "$PUT_URL" --data-binary @sample.wav > /dev/null

# 3. complete — server verifies against storage, registers Media
FILE_ID=$(curl -s -X POST "http://localhost:8000/api/v1/uploads/$SESSION_ID/complete" \
  -H "Content-Type: application/json" -d '{"parts":[]}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['file_id'])")

curl -s -X POST "http://localhost:8000/api/v1/media/transcribe/$FILE_ID" | python -m json.tool
```

## Local development

Нужны **uv** и системный **FFmpeg**.

```bash
cd backend
uv sync                                        # venv из uv.lock
uv run uvicorn src.api.main:app --reload
uv run pytest
uv run ruff check . && uv run black --check .   # перед коммитом
```

## Configuration

Всё через env (см. [`backend/.env.example`](backend/.env.example)). Точки подмены:

| Variable | Values | Effect |
|---|---|---|
| `DATABASE_URL` | full URL | Внешний/managed Postgres «по ссылке» (иначе собирается из `DB_*`) |
| `BROKER_PROVIDER` / `BROKER_URL` | `redis`\|`nats` | Транспорт брокера |
| `TRANSCRIBER_PROVIDER` | `local`\|`remote` | In-process faster-whisper vs внешний ASR |
| `TRANSCRIBER_MODEL` / `_DEVICE` / `_COMPUTE_TYPE` | — | `base`…`large-v3`; `cpu`/`cuda`; `int8`/`float16` |
| `DIARIZER_PROVIDER` | `off`\|`stub`\|`pyannote` | Разделение спикеров |
| `LLM_PROVIDER` | `off`\|`local`\|`remote` | Уровень 3 каскада (при `off` работают уровни 1-2) |
| `STORAGE_PROVIDER` | `local`\|`s3` | Хранение артефактов |

## GPU / CUDA

Runtime-стейдж Dockerfile на `nvidia/cuda:*-cudnn-runtime`,
`TRANSCRIBER_DEVICE=cuda` + `TRANSCRIBER_COMPUTE_TYPE=float16`, запуск с `--gpus all`.
CUDA OOM отдаёт HTTP `507` с подсказкой (меньше модель / int8 / CPU).

---

## Design decisions & tradeoffs

**Outbox вместо прямого publish.** Запись в БД и публикация в брокер не атомарны.
Цена — лишняя таблица и relay-процесс. Взамен — job не теряется.

**Redis, а не Kafka.** Для текущего throughput Kafka — овер-инжиниринг:
партиционирование и ретеншен не нужны, а операционная стоимость высокая.
`BROKER_PROVIDER` оставляет дверь открытой.

**Граф агентов, а не chain.** Оправдан только тем, что четыре детектора работают
параллельно и конфликтуют — нужен арбитраж. Будь они последовательными, хватило бы
обычного пайплайна.

**Каскад вместо «LLM на всё».** LLM на каждом фрагменте дал бы лучшее качество и
неприемлемую стоимость. Каскад теряет доли процента recall и экономит порядок.

**Монолит с гексагональной архитектурой, а не микросервисы.** Один продукт, одна
очередь. Границы обеспечены портами, а не сетью. Разделение возможно позже без
переписывания.

**pgvector, а не отдельная vector DB.** Postgres уже есть; отдельный сервис —
плюс один компонент в эксплуатацию без выигрыша на текущих объёмах.

---

## Roadmap

Порядок намеренный: надёжность и eval раньше AI-фич, иначе улучшения нечем мерить.

**MVP (продукт)**
- **Step 1 ✅** Scaffold: архитектура, uv, Docker, DB/миграции, порты, upload + transcribe
- **Step 2 ✅** Репозитории + jobs/timeline роутеры
- **Step 3 ✅** Outbox repository + relay publish
- **Step 4 ✅** Pipeline core (BasePlugin/runner/registry) + Ingest/Transcribe/Diarize end-to-end, FastStream consumer в worker
- **Step 5 ✅** Project/Artifact слой (`projects`, `artifacts` таблицы, project-scoped S3 keys) +
  диаризация на речевые turn'ы + silence-детекция по гэпам между turn'ами → регионы `auto_cut`,
  вырезание тишины перед транскрипцией (Ingest → Denoise → Diarize → CutSilence → Transcribe)
- **Step 6 ✅** Bad-take детекция на fuzzy (thefuzz), без LLM → регионы `review`.
  Дубли никогда не режутся автоматически — все кандидаты помечаются `REVIEW/ALTERNATE_TAKE`
  с общим `take_group`, финальное решение (какой дубль оставить) — за автором в UI
- **Step 7** Экспорт: FFmpeg concat + pedalboard мастеринг (noise → EQ → compressor → LUFS)

Шаг 6 намеренно без LLM: fuzzy даёт baseline для сравнения и служит fallback'ом.

**Инженерные слои**
- Надёжность: idempotency, circuit breaker, DLQ, graceful degradation, OTel
- Eval-harness + CI-гейт по F1
- Chunked processing (fan-out/fan-in) + WebSocket-прогресс
- LLM-метрики (`llm_calls`: tokens, cost, latency) + semantic cache на pgvector
- Каскадный router (DSP → statistical → LLM)
- Мультиагентный граф + Arbiter с confidence
- RAG на транскриптах прошлых сессий
- Feedback loop: правки юзера → golden dataset
- S3/MinIO + медальон-слои + nightly DAG + dbt на gold

**Продукт дальше**
- React + wavesurfer.js таймлайн (красный/жёлтый/зелёный), плейбек со скипом; Electron
- CLI (`takeflow trim`)
- Script coach: отдельный эндпоинт — LLM разбирает готовый транскрипт и предлагает,
  что подать интереснее. Вне критического пути обрезки: «интереснее» не мерится
  через precision/recall, поэтому слой держится отдельно от детекции.
