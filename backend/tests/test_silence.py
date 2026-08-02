"""
Silence-cutting logic tests — `build_regions` / `keep_ranges`.

Pure-function tests: no ffmpeg, no diarizer, just turn lists and the region
map they should produce.
"""
from __future__ import annotations

from src.application.pipeline.silence import build_regions, keep_ranges
from src.domain.entities import SpeakerTurn
from src.domain.enums import CutReason, RegionKind


class TestBuildRegions:
    def test_single_turn_spanning_whole_file_has_no_cuts(self):
        turns = [SpeakerTurn(start=0.0, end=10.0, speaker_id="0")]

        regions = build_regions(turns, duration=10.0, min_silence=0.6, padding=0.05)

        assert len(regions) == 1
        assert regions[0].kind is RegionKind.KEEP
        assert regions[0].start == 0.0
        assert regions[0].end == 10.0

    def test_gap_shorter_than_min_silence_is_kept(self):
        turns = [
            SpeakerTurn(start=0.0, end=2.0, speaker_id="0"),
            SpeakerTurn(start=2.3, end=4.0, speaker_id="0"),  # 0.3s gap < 0.6 min
        ]

        regions = build_regions(turns, duration=4.0, min_silence=0.6, padding=0.05)

        assert all(r.kind is RegionKind.KEEP for r in regions)

    def test_gap_longer_than_min_silence_is_cut_with_padding(self):
        turns = [
            SpeakerTurn(start=0.0, end=2.0, speaker_id="0"),
            SpeakerTurn(start=4.0, end=6.0, speaker_id="0"),  # 2s gap
        ]

        regions = build_regions(turns, duration=6.0, min_silence=0.6, padding=0.1)

        cut = [r for r in regions if r.kind is RegionKind.AUTO_CUT]
        assert len(cut) == 1
        assert cut[0].reason is CutReason.SILENCE
        assert cut[0].start == 2.1  # 2.0 + padding
        assert cut[0].end == 3.9  # 4.0 - padding

        keep = [r for r in regions if r.kind is RegionKind.KEEP]
        assert len(keep) == 4  # two turns + two padding slivers

    def test_leading_and_trailing_silence_are_handled(self):
        turns = [SpeakerTurn(start=2.0, end=8.0, speaker_id="0")]

        regions = build_regions(turns, duration=10.0, min_silence=0.6, padding=0.0)

        cut = [r for r in regions if r.kind is RegionKind.AUTO_CUT]
        assert len(cut) == 2
        assert cut[0].start == 0.0 and cut[0].end == 2.0
        assert cut[1].start == 8.0 and cut[1].end == 10.0

    def test_no_speech_at_all_is_entirely_cuttable(self):
        regions = build_regions([], duration=5.0, min_silence=0.6, padding=0.0)

        assert len(regions) == 1
        assert regions[0].kind is RegionKind.AUTO_CUT
        assert regions[0].start == 0.0
        assert regions[0].end == 5.0

    def test_padding_that_would_swallow_the_gap_keeps_it_instead(self):
        turns = [
            SpeakerTurn(start=0.0, end=2.0, speaker_id="0"),
            SpeakerTurn(start=2.8, end=4.0, speaker_id="0"),  # 0.8s gap, min 0.6
        ]

        # Padding of 0.5s on each side would need 1.0s of gap; only 0.8s exists.
        regions = build_regions(turns, duration=4.0, min_silence=0.6, padding=0.5)

        assert all(r.kind is RegionKind.KEEP for r in regions)

    def test_speaker_id_is_attached_to_keep_regions_from_turns(self):
        turns = [SpeakerTurn(start=0.0, end=5.0, speaker_id="SPEAKER_01")]

        regions = build_regions(turns, duration=5.0, min_silence=0.6, padding=0.0)

        assert regions[0].speaker == "SPEAKER_01"

    def test_unsorted_turns_are_handled_in_chronological_order(self):
        turns = [
            SpeakerTurn(start=4.0, end=6.0, speaker_id="0"),
            SpeakerTurn(start=0.0, end=2.0, speaker_id="0"),
        ]

        regions = build_regions(turns, duration=6.0, min_silence=0.6, padding=0.0)

        starts = [r.start for r in regions]
        assert starts == sorted(starts)


class TestKeepRanges:
    def test_extracts_only_keep_regions_as_tuples(self):
        turns = [
            SpeakerTurn(start=0.0, end=2.0, speaker_id="0"),
            SpeakerTurn(start=4.0, end=6.0, speaker_id="0"),
        ]
        regions = build_regions(turns, duration=6.0, min_silence=0.6, padding=0.0)

        ranges = keep_ranges(regions)

        assert ranges == [(0.0, 2.0), (4.0, 6.0)]
