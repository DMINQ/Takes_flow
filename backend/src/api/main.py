"""
TakeFlow API — FastAPI application assembly.

Routers register under /api/v1. The worker and relay are separate processes
(src.worker.main / src.worker.relay) and do not import this module.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import jobs, media, projects, timeline, uploads
from src.settings.config import core_settings, storage_settings

logging.basicConfig(
    level=core_settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("takeflow.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage_settings.require_secure_presign_secret(core_settings.debug)
    logger.info("%s API starting (debug=%s)", core_settings.name, core_settings.debug)
    yield
    logger.info("%s API shutting down", core_settings.name)


app = FastAPI(
    title="TakeFlow API",
    description="AI-assisted voiceover editing: transcription, silence & bad-take detection, export.",
    version="0.1.0",
    debug=core_settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=core_settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Everything under a versioned prefix.
app.include_router(uploads.router, prefix="/api/v1")
app.include_router(media.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(timeline.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")


@app.get("/health", tags=["meta"], summary="Liveness/readiness probe")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": core_settings.name}
