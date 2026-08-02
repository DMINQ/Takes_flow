# =============================================================================
# TakeFlow backend — multi-stage build with uv.
#
# builder stage: installs the locked venv with uv (cached independently of code).
# runtime stage: slim image with ffmpeg + the prebuilt venv, no uv, no toolchain.
#
# The same image runs the API, the worker, and the outbox relay — only the
# container `command` differs (see docker-compose.yml).
#
# Build context is ./backend (see docker-compose.yml `build.context`); all
# COPY paths below are relative to that context, not to this Dockerfile.
# =============================================================================

# ---- builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

# uv: fast, lockfile-driven installs. Pinned via the official distroless copy.
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Resolve deps first (no project) so this layer caches across source edits.
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# ffmpeg (media probe/convert) + libsndfile (pedalboard/pydub) + libmagic (MIME sniff).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The prebuilt virtualenv from the builder.
COPY --from=builder /app/.venv /app/.venv

# App source + migrations + entrypoint.
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runtime dirs (also backed by volumes in compose).
RUN mkdir -p /data /models

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
# Default command = API. Worker/relay override this in compose.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# -----------------------------------------------------------------------------
# GPU: base the runtime stage on nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04,
# install python+ffmpeg there, set TRANSCRIBER_DEVICE=cuda / COMPUTE_TYPE=float16,
# and run with `--gpus all`. CTranslate2 wheels bundle the CUDA libs.
# -----------------------------------------------------------------------------
