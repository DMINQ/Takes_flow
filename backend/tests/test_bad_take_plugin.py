"""
BadTakePlugin tests — context wiring only (grouping logic covered by
test_bad_take.py). Confirms the plugin populates `context.phrases` and merges
review regions into whatever CutSilence already put in `context.regions`.
"""
from __future__ import annotations

from src.application.pipeline.plugins.bad_take import BadTakePlugin
from src.domain.dto import PipelineContext
from src.domain.entities import TimelineRegion, Word
from src.domain.enums import RegionKind
from src.settings.config import AnalysisSettings


def _context(words: list[Word], regions: list[TimelineRegion]) -> PipelineContext:
    return PipelineContext(
        job_id="job-1",
        project_id="project-1",
        media_id="media-1",
        input_path="/tmp/in.wav",
        original_filename="in.wav",
        words=words,
        regions=regions,
    )


def _word(text: str, start: float, end: float) -> Word:
    return Word(text=text, start=start, end=end, probability=0.95)


class TestBadTakePlugin:
    async def test_populates_phrases_and_flags_duplicates_as_review(self):
        plugin = BadTakePlugin(AnalysisSettings())

        take_1 = [_word(w, i, i + 0.4) for i, w in enumerate(["this", "is", "the", "line"])]
        take_2 = [_word(w, i + 10, i + 10.4) for i, w in enumerate(["this", "is", "the", "line"])]
        context = _context(
            words=take_1 + take_2,
            regions=[TimelineRegion(start=0.0, end=14.0, kind=RegionKind.KEEP)],
        )

        result = await plugin.run(context)

        assert len(result.phrases) == 2
        review = [r for r in result.regions if r.kind is RegionKind.REVIEW]
        assert len(review) == 2

    async def test_no_duplicates_leaves_regions_untouched(self):
        plugin = BadTakePlugin(AnalysisSettings())
        base_regions = [TimelineRegion(start=0.0, end=5.0, kind=RegionKind.KEEP)]
        words = [_word(w, i, i + 0.4) for i, w in enumerate(["completely", "unique", "sentence"])]

        context = _context(words=words, regions=base_regions)
        result = await plugin.run(context)

        assert result.regions == base_regions
