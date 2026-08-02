"""
Audio engine adapter — FFmpeg (probe/assemble) + pedalboard (preprocess/master).

Implements AudioEnginePort. Only `probe_duration` and `preprocess` are needed for
Phase 1's ingest; `assemble` and `master` are the Phase 4 export path and are
stubbed with clear NotImplementedError until then, so the port stays honest.
"""
from __future__ import annotations

import logging
from pathlib import Path

import ffmpeg

from src.domain.errors import AudioProcessingError

logger = logging.getLogger(__name__)


class FfmpegPedalboardEngine:
    """FFmpeg + pedalboard implementation of AudioEnginePort."""

    def probe_duration(self, media_path: Path) -> float:
        """Read container duration via ffprobe. Raises AudioProcessingError on bad input."""
        try:
            info = ffmpeg.probe(str(media_path))
        except ffmpeg.Error as exc:  # unreadable/corrupt/unsupported
            detail = exc.stderr.decode(errors="ignore") if exc.stderr else str(exc)
            raise AudioProcessingError(f"Could not probe media: {detail}") from exc
        try:
            return float(info["format"]["duration"])
        except (KeyError, ValueError) as exc:
            raise AudioProcessingError("Media has no readable duration.") from exc

    def preprocess(self, media_path: Path, out_path: Path) -> Path:
        """
        Denoise + normalize a working copy for more accurate transcription.

        Phase 2 fills this in with pedalboard (NoiseGate/EQ/normalize). For now it
        returns the source unchanged so ingest works end-to-end.
        """
        logger.debug("preprocess: passthrough (pedalboard chain lands in Phase 2)")
        return media_path

    def assemble(self, media_path: Path, keep_ranges: list[tuple[float, float]], out_path: Path) -> Path:
        """
        Concatenate `keep_ranges` (seconds, in order) into one continuous file.

        Used both by silence cutting (Step 5) and by the final export (Step 7,
        where `keep_ranges` also excludes user-reviewed bad takes). Built with
        ffmpeg's `trim`/`concat` filters so it's a single process invocation
        regardless of how many ranges there are.
        """
        if not keep_ranges:
            raise AudioProcessingError("No ranges to keep — assemble would produce an empty file.")

        stream = ffmpeg.input(str(media_path))
        segments = []
        for start, end in keep_ranges:
            segment = stream.audio.filter("atrim", start=start, end=end).filter("asetpts", "PTS-STARTPTS")
            segments.append(segment)

        joined = ffmpeg.concat(*segments, v=0, a=1) if len(segments) > 1 else segments[0]
        try:
            (
                ffmpeg.output(joined, str(out_path))
                .overwrite_output()
                .run(quiet=True)
            )
        except ffmpeg.Error as exc:
            detail = exc.stderr.decode(errors="ignore") if exc.stderr else str(exc)
            raise AudioProcessingError(f"Could not assemble kept ranges: {detail}") from exc
        return out_path

    def master(self, media_path: Path, out_path: Path) -> Path:
        raise NotImplementedError("Mastering chain is implemented in Phase 4.")
