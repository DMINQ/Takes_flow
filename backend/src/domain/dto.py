"""
PipelineContext — the single DTO threaded through every pipeline plugin.

Each plugin reads what it needs and enriches the context, then returns it. This
is the backbone of the plugin architecture: adding a stage never changes the
signatures of the others. Kept as a pydantic model so it validates and serializes
cleanly (useful for logging/debugging a run).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.entities import Phrase, Speaker, TimelineRegion, Word


class PipelineContext(BaseModel):
    """Mutable state passed stage-to-stage through a pipeline run."""

    # --- Identity / inputs (set at construction) ---
    job_id: str
    media_id: str
    input_path: str = Field(..., description="Absolute path to the source media on the worker.")
    original_filename: str
    language: str | None = None

    # --- Ingest stage ---
    duration: float | None = None
    # Working audio path after pre-processing (denoise/normalize) — plugins update this.
    working_audio_path: str | None = None
    # Extra track paths for multi-track sources.
    audio_tracks: list[str] = Field(default_factory=list)

    # --- Transcription stage ---
    detected_language: str | None = None
    language_probability: float | None = None
    words: list[Word] = Field(default_factory=list)
    phrases: list[Phrase] = Field(default_factory=list)

    # --- Diarization stage ---
    speakers: list[Speaker] = Field(default_factory=list)

    # --- Analysis stages (silence / bad-take) ---
    regions: list[TimelineRegion] = Field(default_factory=list)

    # --- Export stage ---
    export_selection: list[str] = Field(
        default_factory=list,
        description="Region ids/ranges the user chose to keep (populated for export jobs).",
    )
    output_path: str | None = None

    # --- Bookkeeping ---
    temp_files: list[str] = Field(default_factory=list, description="Cleaned up by the runner in finally.")
    metadata: dict[str, object] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}
