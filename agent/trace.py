"""Emitting a trace: one JSON line per run, to the log and to the volume, and the same bytes in the response."""

import logging
from pathlib import Path

from agent.schemas import RunTrace

log = logging.getLogger("kira.trace")

TRACE_FILE = "runs.jsonl"


def render(trace: RunTrace) -> str:
    """The one serialisation. There is no redacted variant, because the schema has nothing to redact. (D-012)"""
    return trace.model_dump_json()


def emit(trace: RunTrace, directory: Path | None = None) -> str:
    """Log it, persist it if a volume is configured, and hand back exactly what was written."""
    line = render(trace)
    log.info(line)

    if directory is not None:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / TRACE_FILE).open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            # A full or read-only volume degrades observability; it must not fail a screening run.
            log.warning("trace not persisted: %s", exc)

    return line
