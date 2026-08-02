"""
Silence-cutting logic — pure functions over speaker turns.

Kept free of I/O so the region-building rules (padding, minimum silence
duration) are unit-testable without ffmpeg or a diarizer. `CutSilencePlugin`
is the only caller; it supplies turns from `DiarizerPort` and settings from
`AnalysisSettings`.
"""
from __future__ import annotations

from src.domain.entities import SpeakerTurn, TimelineRegion
from src.domain.enums import CutReason, RegionKind


def _handle_gap(
    start: float, end: float, *, min_silence: float, padding: float, regions: list[TimelineRegion]
) -> None:
    """Classify one non-speech span as KEEP (too short to bother) or AUTO_CUT.

    A cuttable gap keeps `padding` seconds of silence on each side (so the cut
    doesn't clip right up against speech) and marks only the middle as
    AUTO_CUT/SILENCE.
    """
    length = end - start
    if length <= 0:
        return
    if length < min_silence:
        regions.append(TimelineRegion(start=start, end=end, kind=RegionKind.KEEP))
        return

    cut_start = start + padding
    cut_end = end - padding
    if cut_end <= cut_start:
        # Padding would swallow the whole gap — not worth cutting.
        regions.append(TimelineRegion(start=start, end=end, kind=RegionKind.KEEP))
        return

    if cut_start > start:
        regions.append(TimelineRegion(start=start, end=cut_start, kind=RegionKind.KEEP))
    regions.append(
        TimelineRegion(start=cut_start, end=cut_end, kind=RegionKind.AUTO_CUT, reason=CutReason.SILENCE)
    )
    if end > cut_end:
        regions.append(TimelineRegion(start=cut_end, end=end, kind=RegionKind.KEEP))


def build_regions(
    turns: list[SpeakerTurn], duration: float, *, min_silence: float, padding: float
) -> list[TimelineRegion]:
    """Build a full KEEP/AUTO_CUT region map from speech turns plus the gaps between them.

    Turns are the source of truth for what is speech; everything else is a
    candidate for silence removal. Turns are assumed non-overlapping (true for
    the stub and for pyannote's diarization output); overlapping input is
    tolerated by clamping the cursor forward rather than going backwards.
    """
    regions: list[TimelineRegion] = []
    cursor = 0.0
    for turn in sorted(turns, key=lambda t: t.start):
        _handle_gap(cursor, turn.start, min_silence=min_silence, padding=padding, regions=regions)
        if turn.end > turn.start:
            regions.append(
                TimelineRegion(start=turn.start, end=turn.end, kind=RegionKind.KEEP, speaker=turn.speaker_id)
            )
        cursor = max(cursor, turn.end)
    _handle_gap(cursor, duration, min_silence=min_silence, padding=padding, regions=regions)
    return regions


def keep_ranges(regions: list[TimelineRegion]) -> list[tuple[float, float]]:
    """Extract the (start, end) spans an assembler should retain, in order."""
    return [(r.start, r.end) for r in regions if r.kind is RegionKind.KEEP and r.end > r.start]
