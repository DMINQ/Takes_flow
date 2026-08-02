"""
Runner — executes an ordered list of plugins over one PipelineContext.

Owns the cross-cutting concerns every pipeline needs: sequential execution,
per-stage logging/progress, error translation into a job FAILED status, and
temp-file cleanup. Individual plugins stay free of this bookkeeping.
"""
from __future__ import annotations

import logging
import os

from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.errors import DomainError
from src.domain.ports.repositories import JobRepository

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Wraps a plugin failure with the stage name that raised it."""

    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(f"Stage '{stage}' failed: {cause}")
        self.stage = stage
        self.cause = cause


class Runner:
    """Runs `plugins` in order over a context, reporting progress via `job_repo`."""

    def __init__(self, plugins: list[BasePlugin], job_repo: JobRepository | None = None) -> None:
        self._plugins = plugins
        self._jobs = job_repo

    async def run(self, context: PipelineContext) -> PipelineContext:
        total = len(self._plugins) or 1
        try:
            for index, plugin in enumerate(self._plugins):
                logger.info("job %s: running stage '%s'", context.job_id, plugin.name)
                try:
                    context = await plugin.run(context)
                except DomainError:
                    raise
                except Exception as exc:  # noqa: BLE001 - convert to a diagnosable PipelineError
                    raise PipelineError(plugin.name, exc) from exc

                if self._jobs is not None:
                    await self._jobs.set_progress(context.job_id, (index + 1) / total)
            return context
        finally:
            self._cleanup(context)

    @staticmethod
    def _cleanup(context: PipelineContext) -> None:
        """Best-effort removal of scratch files plugins registered along the way."""
        for path in context.temp_files:
            try:
                os.remove(path)
            except OSError:
                pass
