"""
BadTakePlugin — finds re-recorded (duplicate) phrases and flags them for review.

Runs after TranscribePlugin: it needs `context.words` to build phrases and
compare their text. Never auto-cuts — every duplicate becomes a REVIEW region
(see `application.pipeline.bad_take`) so the user picks which take to keep.
"""
from __future__ import annotations

from src.application.pipeline.bad_take import (
    build_phrases,
    build_review_regions,
    find_duplicate_groups,
    merge_review_regions,
)
from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.settings.config import AnalysisSettings


class BadTakePlugin(BasePlugin):
    """Flags fuzzy-duplicate phrases as REVIEW regions, without cutting anything."""

    name = "bad_take"

    def __init__(self, settings: AnalysisSettings) -> None:
        self._threshold = settings.bad_take_similarity_threshold
        self._min_words = settings.bad_take_min_words

    async def run(self, context: PipelineContext) -> PipelineContext:
        phrases = build_phrases(context.words)
        context.phrases = phrases

        groups = find_duplicate_groups(phrases, threshold=self._threshold, min_words=self._min_words)
        if not groups:
            return context

        review_regions = build_review_regions(groups)
        context.regions = merge_review_regions(context.regions, review_regions)
        return context
