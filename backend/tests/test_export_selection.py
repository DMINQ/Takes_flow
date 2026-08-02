"""
Export selection logic tests — `resolve_export_ranges` / `parse_export_selection`.

Pure-function tests: no ffmpeg, no database.
"""
from __future__ import annotations

from src.application.pipeline.export_selection import parse_export_selection, resolve_export_ranges
from src.domain.entities import TimelineRegion
from src.domain.enums import CutReason, RegionKind


class TestResolveExportRanges:
    def test_keeps_keep_regions_and_drops_auto_cut(self):
        regions = [
            TimelineRegion(start=0.0, end=2.0, kind=RegionKind.KEEP),
            TimelineRegion(start=2.0, end=3.0, kind=RegionKind.AUTO_CUT, reason=CutReason.SILENCE),
            TimelineRegion(start=3.0, end=5.0, kind=RegionKind.KEEP),
        ]

        ranges = resolve_export_ranges(regions)

        assert ranges == [(0.0, 2.0), (3.0, 5.0)]

    def test_review_regions_are_kept_by_default(self):
        regions = [
            TimelineRegion(start=0.0, end=2.0, kind=RegionKind.KEEP),
            TimelineRegion(
                start=2.0, end=4.0, kind=RegionKind.REVIEW, reason=CutReason.ALTERNATE_TAKE, take_group="g1"
            ),
        ]

        ranges = resolve_export_ranges(regions)

        assert ranges == [(0.0, 4.0)]

    def test_review_region_in_cut_set_is_dropped(self):
        regions = [
            TimelineRegion(start=0.0, end=2.0, kind=RegionKind.KEEP),
            TimelineRegion(
                start=2.0, end=4.0, kind=RegionKind.REVIEW, reason=CutReason.ALTERNATE_TAKE, take_group="g1"
            ),
            TimelineRegion(start=4.0, end=6.0, kind=RegionKind.KEEP),
        ]

        ranges = resolve_export_ranges(regions, cut_review_regions={(2.0, 4.0)})

        assert ranges == [(0.0, 2.0), (4.0, 6.0)]

    def test_empty_regions_produce_no_ranges(self):
        assert resolve_export_ranges([]) == []

    def test_zero_length_regions_are_skipped(self):
        regions = [TimelineRegion(start=1.0, end=1.0, kind=RegionKind.KEEP)]

        assert resolve_export_ranges(regions) == []


class TestParseExportSelection:
    def test_parses_valid_cut_entries(self):
        selection = ["cut:2.0:4.0", "cut:10.5:12.25"]

        cut = parse_export_selection(selection)

        assert cut == {(2.0, 4.0), (10.5, 12.25)}

    def test_ignores_malformed_entries(self):
        selection = ["cut:2.0", "not-a-cut", "cut:a:b", "cut:1.0:2.0"]

        cut = parse_export_selection(selection)

        assert cut == {(1.0, 2.0)}

    def test_empty_list_returns_empty_set(self):
        assert parse_export_selection([]) == set()
