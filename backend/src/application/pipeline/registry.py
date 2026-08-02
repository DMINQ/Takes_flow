"""
PipelineRegistry — maps a JobKind to the ordered list of plugins that run for it.

Centralizing this mapping keeps `Runner` generic (it just iterates whatever list
it's given) and keeps stage order/composition in one place instead of scattered
across the worker. Building the list is deferred to a factory function so
plugins can pull their dependencies (ports) from settings/providers lazily,
which matters for the transcriber: loading it eagerly at import time would pay
the model-load cost even for export-only runs.
"""
from __future__ import annotations

from collections.abc import Callable

from src.application.pipeline.plugin import BasePlugin
from src.domain.enums import JobKind

PluginFactory = Callable[[], list[BasePlugin]]


class PipelineRegistry:
    """Registers a plugin-list factory per JobKind and builds pipelines on demand."""

    def __init__(self) -> None:
        self._factories: dict[JobKind, PluginFactory] = {}

    def register(self, kind: JobKind, factory: PluginFactory) -> None:
        self._factories[kind] = factory

    def build(self, kind: JobKind) -> list[BasePlugin]:
        factory = self._factories.get(kind)
        if factory is None:
            raise KeyError(f"No pipeline registered for job kind '{kind.value}'.")
        return factory()


#: Process-wide registry populated at import time by `application.pipeline.pipelines`.
registry = PipelineRegistry()
