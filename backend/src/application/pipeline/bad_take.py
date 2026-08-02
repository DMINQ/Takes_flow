"""
Bad-take detection — pure functions over transcribed words.

Groups words into phrases, then finds phrases that are near-duplicates of each
other (an actor re-recording the same line). Kept free of I/O so the grouping
and similarity rules are unit-testable without a real transcriber.
`BadTakePlugin` is the only caller.

Every duplicate is marked REVIEW/ALTERNATE_TAKE, never auto-cut: which take is
best is a judgment call (delivery, timing) fuzzy text matching can't make, so
the user listens to each candidate in the UI and decides.
"""
from __future__ import annotations

import uuid

from thefuzz import fuzz

from src.domain.entities import Phrase, TimelineRegion, Word
from src.domain.enums import CutReason, RegionKind


def build_phrases(words: list[Word], *, max_pause: float = 0.8) -> list[Phrase]:
    """Group consecutive words into phrases, splitting on pauses longer than `max_pause`.

    A simple, dependency-free stand-in for sentence segmentation: takes lasso
    boundaries at silence rather than punctuation, since re-recorded lines are
    what we're grouping around, not grammar.
    """
    phrases: list[Phrase] = []
    current: list[Word] = []

    for word in words:
        if current and word.start - current[-1].end > max_pause:
            phrases.append(_phrase_from_words(current))
            current = []
        current.append(word)

    if current:
        phrases.append(_phrase_from_words(current))
    return phrases


def _phrase_from_words(words: list[Word]) -> Phrase:
    return Phrase(
        text=" ".join(w.text.strip() for w in words).strip(),
        start=words[0].start,
        end=words[-1].end,
        words=list(words),
        speaker=words[0].speaker,
    )


def find_duplicate_groups(
    phrases: list[Phrase], *, threshold: int = 85, min_words: int = 3
) -> list[list[Phrase]]:
    """Cluster phrases that are near-duplicates of each other by text similarity.

    Compares every phrase against every other (there are only ever a few
    hundred phrases per recording, so O(n^2) is cheap), using union-find so a
    chain of similar phrases (A~B, B~C) ends up in one group even if A and C
    alone fall just under the threshold. Phrases shorter than `min_words` are
    skipped — short filler ("um", "okay") matches everything and isn't a take.
    """
    candidates = [p for p in phrases if len(p.words) >= min_words]
    parent = list(range(len(candidates)))

    def find(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if fuzz.ratio(candidates[i].text.lower(), candidates[j].text.lower()) >= threshold:
                union(i, j)

    groups: dict[int, list[Phrase]] = {}
    for i, phrase in enumerate(candidates):
        groups.setdefault(find(i), []).append(phrase)

    return [group for group in groups.values() if len(group) > 1]


def merge_review_regions(
    base_regions: list[TimelineRegion], review_regions: list[TimelineRegion]
) -> list[TimelineRegion]:
    """Splice REVIEW regions into an existing KEEP/AUTO_CUT region map.

    Review phrases fall inside spans silence-cutting already marked KEEP (a
    duplicate line is still speech). For each KEEP region, any review region
    it fully contains carves out a REVIEW slice, leaving KEEP slivers before
    and after; AUTO_CUT regions pass through untouched since a cut span was
    never speech to begin with.
    """
    result: list[TimelineRegion] = []
    for region in sorted(base_regions, key=lambda r: r.start):
        if region.kind is not RegionKind.KEEP:
            result.append(region)
            continue

        overlapping = sorted(
            (r for r in review_regions if r.start >= region.start and r.end <= region.end),
            key=lambda r: r.start,
        )
        if not overlapping:
            result.append(region)
            continue

        cursor = region.start
        for review in overlapping:
            if review.start > cursor:
                result.append(TimelineRegion(start=cursor, end=review.start, kind=RegionKind.KEEP))
            result.append(review)
            cursor = max(cursor, review.end)
        if cursor < region.end:
            result.append(TimelineRegion(start=cursor, end=region.end, kind=RegionKind.KEEP))

    return result


def build_review_regions(groups: list[list[Phrase]]) -> list[TimelineRegion]:
    """Mark every phrase in every duplicate group as REVIEW — never auto-cut.

    Each group gets its own `take_group` id so the UI can present its members
    together (e.g. as a stack the user picks one take from).
    """
    regions: list[TimelineRegion] = []
    for group in groups:
        take_group = uuid.uuid4().hex
        for phrase in sorted(group, key=lambda p: p.start):
            regions.append(
                TimelineRegion(
                    start=phrase.start,
                    end=phrase.end,
                    kind=RegionKind.REVIEW,
                    reason=CutReason.ALTERNATE_TAKE,
                    take_group=take_group,
                    text=phrase.text,
                    speaker=phrase.speaker,
                )
            )
    return regions
