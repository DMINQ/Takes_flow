"""HTTP request/response schemas for media endpoints — the API contract."""
from __future__ import annotations

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    file_id: str = Field(..., description="Reference this media in later calls.")
    filename: str
    size_bytes: int
    content_type: str | None = None


class WordOut(BaseModel):
    word: str
    start: float
    end: float
    probability: float
    speaker: str | None = None


class TranscriptionResponse(BaseModel):
    file_id: str
    language: str
    language_probability: float
    duration: float
    words: list[WordOut]
