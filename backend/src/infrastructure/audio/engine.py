"""
Audio engine adapter — FFmpeg (probe/assemble) + pedalboard/pyloudnorm (preprocess/master).

Implements AudioEnginePort.
"""
from __future__ import annotations

import logging
from pathlib import Path

import ffmpeg
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from pedalboard import Compressor, HighpassFilter, NoiseGate, PeakFilter, Pedalboard

from src.domain.errors import AudioProcessingError
from src.settings.config import MasteringSettings

logger = logging.getLogger(__name__)


class FfmpegPedalboardEngine:
    """FFmpeg + pedalboard implementation of AudioEnginePort."""

    def __init__(self, mastering: MasteringSettings | None = None) -> None:
        self._mastering = mastering or MasteringSettings()

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
        """
        Mastering chain: noise gate -> highpass -> peak EQ -> compressor -> LUFS normalize.

        Runs entirely on decoded samples (pedalboard/pyloudnorm operate on
        numpy arrays), so the file is read once via soundfile and written once
        at the end. LUFS normalization is a two-pass measure-then-gain-adjust
        step (pyloudnorm only measures; pedalboard has no loudness target),
        which is why it's applied after the pedalboard chain rather than as
        one more plugin in it.
        """
        settings = self._mastering
        try:
            audio, sample_rate = sf.read(str(media_path), always_2d=True)
        except Exception as exc:  # noqa: BLE001 - soundfile raises a wide surface
            raise AudioProcessingError(f"Could not read audio for mastering: {exc}") from exc

        board = Pedalboard(
            [
                NoiseGate(threshold_db=settings.noise_gate_threshold_db, ratio=1.5, release_ms=250),
                HighpassFilter(cutoff_frequency_hz=settings.highpass_hz),
                PeakFilter(
                    cutoff_frequency_hz=settings.eq_frequency_hz,
                    gain_db=settings.eq_gain_db,
                    q=settings.eq_q,
                ),
                Compressor(
                    threshold_db=settings.compressor_threshold_db,
                    ratio=settings.compressor_ratio,
                    attack_ms=5,
                    release_ms=100,
                ),
            ]
        )
        # pedalboard expects (channels, samples); soundfile reads (samples, channels).
        processed = board(audio.T, sample_rate).T

        try:
            meter = pyln.Meter(sample_rate)
            current_loudness = meter.integrated_loudness(processed)
            if current_loudness > float("-inf"):
                processed = pyln.normalize.loudness(processed, current_loudness, settings.target_lufs)
        except Exception as exc:  # noqa: BLE001 - e.g. a silent/too-short file
            logger.warning("LUFS normalization skipped for %s: %s", media_path, exc)

        processed = np.clip(processed, -1.0, 1.0)
        try:
            sf.write(str(out_path), processed, sample_rate)
        except Exception as exc:  # noqa: BLE001
            raise AudioProcessingError(f"Could not write mastered audio: {exc}") from exc
        return out_path
