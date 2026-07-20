# TakeFlow

AI-assisted voiceover / dialogue editor (Mini-NLE). Transcribes audio, removes
silence, detects bad takes, flags alternative takes for review, and exports a
post-processed final file.

> **Status: Step 1 (scaffold) complete** — clean/hexagonal architecture, uv,
> multi-stage Docker, async Postgres + Alembic, FastStream/Redis outbox skeleton,
> and Phase 1 upload + word-level transcription wired through ports/adapters.

## Architecture

Hexagonal (ports & adapters). Dependencies point inward: `api`/`worker` →
`application` → `domain`; `infrastructure` implements the domain's ports. Swapping
any external dependency (local↔remote Whisper, local↔remote/managed Postgres,
fs↔S3, stub↔pyannote) is a **settings change**, not a code change.

```
backend/
├── pyproject.toml / uv.lock       # deps via uv (canonical)
├── Dockerfile                     # multi-stage, uv builder → slim runtime
├── deploy/entrypoint.sh           # alembic upgrade head → exec CMD
├── alembic/                       # async migrations
└── src/
    ├── domain/                    # pure core (no deps)
    │   ├── entities.py            # Media, Job, Word, Phrase, TimelineRegion, Speaker
    │   ├── enums.py               # JobStatus, RegionKind(keep/auto_cut/review), ...
    │   ├── dto.py                 # PipelineContext — threaded through every plugin
    │   ├── errors.py
    │   └── ports/                 # TranscriberPort, DiarizerPort, StoragePort,
    │                              #   AudioEnginePort, LLMPort, *Repository
    ├── application/               # use-cases + pipeline (Phase 2/4)
    ├── infrastructure/            # adapters implementing the ports
    │   ├── db.py                  # async engine/session, Base
    │   ├── models.py              # ORM (media/jobs/timeline_regions/outbox)
    │   ├── transcribers/local.py  # faster-whisper (TranscriberPort)
    │   ├── diarizers/stub.py      # single-speaker (DiarizerPort) — pyannote later
    │   ├── storage/local.py       # filesystem (StoragePort)
    │   └── audio/engine.py        # ffmpeg + pedalboard (AudioEnginePort)
    ├── api/                       # FastAPI: main, deps, routers/, schemas/
    ├── worker/                    # python -m src.worker.main / .relay
    └── settings/                  # config.py (composed) + providers.py (adapter selection)
```

Four representations of "a thing", kept separate on purpose:
**domain entities** (business) · **PipelineContext** (pipeline DTO) ·
**api/schemas** (HTTP contract) · **infrastructure/models** (ORM).

### Background work: transactional outbox → broker → worker

1. **API** writes `Media` + `Job` + `OutboxEvent` in one DB transaction, returns a `job_id`.
2. **relay** (`src.worker.relay`) publishes pending outbox events to the broker (FastStream/Redis).
3. **worker** (`src.worker.main`) consumes, claims the job (`SELECT … FOR UPDATE`), runs the pipeline.

FastStream is used over **Redis** (same decorator API as RabbitMQ, lighter);
`BROKER_PROVIDER=nats` switches transport without code changes.

## Quick start (Docker)

```bash
docker compose up --build
#   API docs:  http://localhost:8000/docs
#   services:  api, worker, relay, db (postgres), redis
```

Migrations run automatically on the `api` container start. The Whisper model
downloads once into the `takeflow-models` volume (shared by api + worker).

### Try it

```bash
FILE_ID=$(curl -s -F "file=@sample.wav" http://localhost:8000/api/v1/media/upload \
  | python -c "import sys,json;print(json.load(sys.stdin)['file_id'])")
curl -s -X POST "http://localhost:8000/api/v1/media/transcribe/$FILE_ID" | python -m json.tool
```

## Configuration

All via env (see [`backend/.env.example`](backend/.env.example)). Key swap points:

| Variable | Values | Effect |
|---|---|---|
| `DATABASE_URL` | full URL | Point at a remote/managed Postgres "by link" (else assembled from `DB_*`). |
| `BROKER_PROVIDER` / `BROKER_URL` | `redis`\|`nats` | Broker transport. |
| `TRANSCRIBER_PROVIDER` | `local`\|`remote` | In-process faster-whisper vs external ASR. |
| `TRANSCRIBER_MODEL` / `_DEVICE` / `_COMPUTE_TYPE` | — | `base`…`large-v3`; `cpu`/`cuda`; `int8`/`float16`. |
| `DIARIZER_PROVIDER` | `off`\|`stub`\|`pyannote` | Speaker separation (pyannote lands later). |
| `LLM_PROVIDER` | `off`\|`local`\|`remote` | Semantic bad-take detection (else string similarity). |
| `STORAGE_PROVIDER` | `local`\|`s3` | Artifact storage. |

## Local development (without Docker)

Requires **uv** and system **FFmpeg**.

```bash
cd backend
uv sync                    # create .venv from uv.lock
uv run uvicorn src.api.main:app --reload
uv run pytest
```

## GPU / CUDA

Base the Dockerfile runtime stage on `nvidia/cuda:*-cudnn-runtime`, set
`TRANSCRIBER_DEVICE=cuda` + `TRANSCRIBER_COMPUTE_TYPE=float16`, run with `--gpus all`.
CUDA OOM returns HTTP `507` with guidance (smaller model / int8 / CPU).

## Roadmap

- **Step 1 ✅** Scaffold: architecture, uv, Docker, DB/migrations, ports/adapters, upload + transcribe.
- **Step 2** API jobs/timeline routers + repositories.
- **Step 3** Outbox repository + relay publish + FastStream consumer + JobService.
- **Step 4** Pipeline core (BasePlugin/runner/registry) + Ingest/Transcribe end-to-end.
- **Phase 2** Silence + bad-take detection plugins → timeline map.
- **Phase 3** React + wavesurfer.js timeline (red/yellow/green), playback skipping cuts; Electron wrapper.
- **Phase 4** Export pipeline: FFmpeg concat + pedalboard mastering (noise → EQ → compressor → LUFS).
```
