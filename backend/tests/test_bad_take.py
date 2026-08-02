"""
Bad-take detection tests — `build_phrases` / `find_duplicate_groups` /
`build_review_regions` / `merge_review_regions`.

Pure-function tests: no transcriber, no thefuzz internals beyond what the
public ratio() call does.
"""
from __future__ import annotations

from src.application.pipeline.bad_take import (
    build_phrases,
    build_review_regions,
    find_duplicate_groups,
    merge_review_regions,
)
from src.domain.entities import TimelineRegion, Word
from src.domain.enums import CutReason, RegionKind


def _word(text: str, start: float, end: float) -> Word:
    return Word(text=text, start=start, end=end, probability=0.95)


class TestBuildPhrases:
    def test_splits_on_long_pauses(self):
        words = [
            _word("hello", 0.0, 0.5),
            _word("world", 0.6, 1.0),
            _word("next", 3.0, 3.5),  # 2s pause > default 0.8
        ]

        phrases = build_phrases(words)

        assert len(phrases) == 2
        assert phrases[0].text == "hello world"
        assert phrases[1].text == "next"

    def test_no_pause_keeps_one_phrase(self):
        words = [_word("a", 0.0, 0.2), _word("b", 0.25, 0.5), _word("c", 0.55, 0.8)]

        phrases = build_phrases(words)

        assert len(phrases) == 1
        assert phrases[0].text == "a b c"
        assert phrases[0].start == 0.0
        assert phrases[0].end == 0.8

    def test_empty_words_produces_no_phrases(self):
        assert build_phrases([]) == []


class TestFindDuplicateGroups:
    def test_finds_near_identical_phrases(self):
        words_a = [_word(w, i, i + 0.4) for i, w in enumerate(["this", "is", "the", "line"])]
        words_b = [_word(w, i + 10, i + 10.4) for i, w in enumerate(["this", "is", "the", "line"])]
        phrases = build_phrases(words_a) + build_phrases(words_b)

        groups = find_duplicate_groups(phrases, threshold=85, min_words=3)

        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_dissimilar_phrases_are_not_grouped(self):
        words_a = [_word(w, i, i + 0.4) for i, w in enumerate(["completely", "different", "sentence"])]
        words_b = [_word(w, i + 10, i + 10.4) for i, w in enumerate(["another", "unrelated", "thought"])]
        phrases = build_phrases(words_a) + build_phrases(words_b)

        groups = find_duplicate_groups(phrases, threshold=85, min_words=3)

        assert groups == []

    def test_short_phrases_below_min_words_are_ignored(self):
        words_a = [_word("ok", 0.0, 0.3), _word("um", 0.4, 0.6)]
        words_b = [_word("ok", 10.0, 10.3), _word("um", 10.4, 10.6)]
        phrases = build_phrases(words_a) + build_phrases(words_b)

        groups = find_duplicate_groups(phrases, threshold=85, min_words=3)

        assert groups == []

    def test_transitive_chain_groups_together(self):
        """A~B and B~C should end up in the same group even if A and C alone are borderline."""
        base = ["the", "quick", "brown", "fox", "jumps"]
        variant_b = ["the", "quick", "brown", "fox", "leaps"]  # close to A
        variant_c = ["the", "quick", "brown", "cat", "leaps"]  # close to B, further from A

        phrases = []
        for offset, words in enumerate([base, variant_b, variant_c]):
            phrases += build_phrases([_word(w, offset * 10 + i, offset * 10 + i + 0.4) for i, w in enumerate(words)])

        groups = find_duplicate_groups(phrases, threshold=70, min_words=3)

        assert len(groups) == 1
        assert len(groups[0]) == 3


class TestBuildReviewRegions:
    def test_marks_every_phrase_in_a_group_as_review_never_auto_cut(self):
        words_a = [_word(w, i, i + 0.4) for i, w in enumerate(["take", "one", "line"])]
        words_b = [_word(w, i + 10, i + 10.4) for i, w in enumerate(["take", "one", "line"])]
        group = build_phrases(words_a) + build_phrases(words_b)

        regions = build_review_regions([group])

        assert len(regions) == 2
        assert all(r.kind is RegionKind.REVIEW for r in regions)
        assert all(r.reason is CutReason.ALTERNATE_TAKE for r in regions)
        assert regions[0].take_group == regions[1].take_group

    def test_different_groups_get_different_take_group_ids(self):
        group_a = build_phrases([_word(w, i, i + 0.4) for i, w in enumerate(["alpha", "line", "text"])]) * 2
        group_b = build_phrases([_word(w, i, i + 0.4) for i, w in enumerate(["beta", "line", "text"])]) * 2

        regions = build_review_regions([group_a, group_b])

        take_groups = {r.take_group for r in regions}
        assert len(take_groups) == 2


class TestMergeReviewRegions:
    def test_splices_review_region_inside_a_keep_region(self):
        base = [TimelineRegion(start=0.0, end=10.0, kind=RegionKind.KEEP)]
        review = [
            TimelineRegion(
                start=4.0, end=6.0, kind=RegionKind.REVIEW, reason=CutReason.ALTERNATE_TAKE, take_group="g1"
            )
        ]

        merged = merge_review_regions(base, review)

        assert len(merged) == 3
        assert merged[0].kind is RegionKind.KEEP and merged[0].start == 0.0 and merged[0].end == 4.0
        assert merged[1].kind is RegionKind.REVIEW
        assert merged[2].kind is RegionKind.KEEP and merged[2].start == 6.0 and merged[2].end == 10.0

    def test_auto_cut_regions_pass_through_untouched(self):
        base = [
            TimelineRegion(start=0.0, end=2.0, kind=RegionKind.AUTO_CUT, reason=CutReason.SILENCE),
            TimelineRegion(start=2.0, end=8.0, kind=RegionKind.KEEP),
        ]

        merged = merge_review_regions(base, [])

        assert merged == base

    def test_review_region_exactly_covering_keep_region_leaves_no_slivers(self):
        base = [TimelineRegion(start=0.0, end=5.0, kind=RegionKind.KEEP)]
        review = [
            TimelineRegion(
                start=0.0, end=5.0, kind=RegionKind.REVIEW, reason=CutReason.ALTERNATE_TAKE, take_group="g1"
            )
        ]

        merged = merge_review_regions(base, review)

        assert len(merged) == 1
        assert merged[0].kind is RegionKind.REVIEW
