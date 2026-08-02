"""
Export selection logic — turn the timeline region map + the user's take
choices into the final list of (start, end) ranges to keep.

Pure functions so the selection rules are unit-testable without ffmpeg or a
database. `AssembleExportPlugin` is the only caller.
"""
from __future__ import annotations

from src.domain.entities import TimelineRegion
from src.domain.enums import RegionKind


def resolve_export_ranges(
    regions: list[TimelineRegion], *, cut_review_regions: set[tuple[float, float]] | None = None
) -> list[tuple[float, float]]:
    """
    Build the final keep-ranges for export.

    KEEP regions are always kept. AUTO_CUT regions (silence) are always
    dropped. REVIEW regions (duplicate takes) default to kept — nothing is
    auto-removed — unless the caller passes their (start, end) in
    `cut_review_regions`, which is how the user's UI choice ("drop this
    take") reaches the pipeline (see PipelineContext.export_selection).
    """
    cut_set = cut_review_regions or set()
    ranges: list[tuple[float, float]] = []
    for region in sorted(regions, key=lambda r: r.start):
        if region.end <= region.start:
            continue
        if region.kind is RegionKind.AUTO_CUT:
            continue
        if region.kind is RegionKind.REVIEW and (region.start, region.end) in cut_set:
            continue
        ranges.append((region.start, region.end))
    return _merge_adjacent(ranges)


def _merge_adjacent(ranges: list[tuple[float, float]], *, epsilon: float = 1e-6) -> list[tuple[float, float]]:
    """Coalesce ranges that touch (or overlap) so assemble() doesn't cut mid-word."""
    if not ranges:
        return []
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + epsilon:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def parse_export_selection(export_selection: list[str]) -> set[tuple[float, float]]:
    """
    Decode `PipelineContext.export_selection` into a set of (start, end) tuples.

    Entries are `"cut:<start>:<end>"` strings — the simplest wire format for a
    job's `params` dict (see JobService.create), naming exactly which REVIEW
    region spans the user chose to drop.
    """
    cut: set[tuple[float, float]] = set()
    for entry in export_selection:
        parts = entry.split(":")
        if len(parts) != 3 or parts[0] != "cut":
            continue
        try:
            cut.add((float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    return cut
