"""
BasePlugin — the unit of work a pipeline `Runner` executes.

Each plugin does one job (ingest, transcribe, diarize, detect silence, ...),
reads what it needs off `PipelineContext` and returns an updated context. Kept
deliberately thin: plugins depend only on domain ports (never on infrastructure
directly), so they're testable with fakes and swappable via settings/providers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.dto import PipelineContext


class BasePlugin(ABC):
    """A single stage of a pipeline run."""

    #: Stable identifier used for logging, registry lookup and progress reporting.
    name: str = "plugin"

    @abstractmethod
    async def run(self, context: PipelineContext) -> PipelineContext:
        """Execute this stage and return the (possibly mutated) context.

        Implementations should raise `src.domain.errors.DomainError` subclasses
        on expected failures so the runner can record a clean job error.
        """
        ...
