"""HTTP request/response schemas for media endpoints — the API contract."""
from __future__ import annotations

from pydantic import BaseModel

# Upload contracts live in api/schemas/uploads.py — clients upload directly to
# storage, so there is no upload request/response body here.


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
