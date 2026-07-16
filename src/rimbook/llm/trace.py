"""LLM response trace logging — append-only, per-project provenance.

Goal: every LLM call RimBook makes (planning, writing, summarization, codex
enrichment, checking) is recorded so that downstream problems — a duplicated
codex entry, a drifted entity id, an out-of-character line — can be traced
back to the exact prompt the model received and the exact text it returned.

Design:
- ``TraceStore`` is bound to a project directory; it appends one JSON object
  per record to ``<project>/.llm_logs/YYYY-MM-DD.jsonl`` (rotated daily).
- ``LLMTrace`` is a context manager. Callers wrap an ``llm.generate*`` call
  and then call :meth:`LLMTrace.record` once (or several times) to persist
  the prompts/response + structured metadata (resolved ids, warnings, …).
- The trace layer never throws into the caller's path: logging is best-effort,
  failures are logged to stderr and swallowed so the writing pipeline is
  unaffected.

Why per-call rather than inside ``LLMClient``? Keeping trace at call sites
gives each stage a chance to attach stage-specific metadata (e.g. the
planner attaches ``resolved_ids``; the enricher attaches ``new_entities``)
that the client has no business knowing about.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .client import GenerationResult, JsonResult, Message

__all__ = ["TraceStore", "LLMTrace", "NULL_TRACE"]

logger = logging.getLogger(__name__)

# Per-process lock so concurrent requests (SSE writer sessions) can safely
# append to the same day's file. One global lock is plenty for the trace
# throughput we generate.
_FILE_LOCK = threading.Lock()


class TraceStore:
    """Append-only provenance log rooted at ``<project>/.llm_logs/``.

    A single ``TraceStore`` per project is cheap to construct and safe to
    share across pipeline components; all appends go through one module-level
    lock and one open/append/close cycle, so fibers don't need their own
    synchronization.
    """

    def __init__(self, project_dir: Path | None) -> None:
        self.project_dir = Path(project_dir) if project_dir is not None else None
        self.root: Path | None = (
            self.project_dir / ".llm_logs" if self.project_dir is not None else None
        )

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def begin(
        self,
        stage: str,
        *,
        project: str = "",
        chapter: int | None = None,
        **meta: Any,
    ) -> "LLMTrace":
        """Open a trace record for *stage* and return a context manager."""
        return LLMTrace(self, stage, project=project, chapter=chapter, **meta)

    def append(self, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            assert self.root is not None
            self.root.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, default=str)
            today = datetime.now().strftime("%Y-%m-%d")
            path = self.root / f"{today}.jsonl"
            with _FILE_LOCK:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as exc:  # pragma: no cover — logging must never raise
            logger.warning("TraceStore.append failed: %s", exc)


class LLMTrace:
    """Context manager wrapping a single LLM call's provenance.

    Usage::

        with self.trace.begin("planner", chapter=number) as t:
            result = self.llm.generate_json(messages, ...)
            t.record(messages, result, resolved_ids={"a": "b"}, warnings=ws)
    """

    def __init__(
        self,
        store: TraceStore,
        stage: str,
        *,
        project: str = "",
        chapter: int | None = None,
        **meta: Any,
    ) -> None:
        self.store = store
        self.stage = stage
        self.project = project
        self.chapter = chapter
        self.meta: dict[str, Any] = dict(meta)
        self.started_at: datetime = datetime.now()
        self._records: list[dict[str, Any]] = []
        self._error: str = ""

    # ------------------------------------------------------------------
    def record(
        self,
        messages: Iterable[Message],
        result: GenerationResult | str | dict[str, Any] | None,
        *,
        resolved_ids: dict[str, str] | None = None,
        warnings: list[str] | None = None,
        model: str | None = None,
    ) -> None:
        """Persist one prompt/response pair for this stage.

        *result* may be a :class:`GenerationResult`, the raw response string
        (for ``generate_json`` callers that already pulled ``content``), a
        parsed JSON dict, or ``None`` (call failed before completion). The
        trace layer keeps whatever shape it received rather than serializing
        assumptions about it.

        *model* lets ``generate_json`` callers (which lose the
        :class:`GenerationResult` wrapper after JSON parsing) record which
        model handled the call. When absent, the trace still recovers the
        model name from a :class:`GenerationResult` payload.
        """
        if not self.store.enabled:
            return
        # Normalize messages for JSON: they are plain dicts of {role, content}.
        msgs = []
        for m in messages or []:
            try:
                msgs.append({"role": m.get("role", ""), "content": m.get("content", "")})
            except AttributeError:
                msgs.append(str(m))

        record: dict[str, Any] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "stage": self.stage,
            "project": self.project,
            "chapter": self.chapter,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "prompt": msgs,
        }
        if model:
            record["model"] = model
        if resolved_ids:
            record["resolved_ids"] = resolved_ids
        if warnings:
            record["warnings"] = list(warnings)

        # result
        if isinstance(result, GenerationResult):
            record["model"] = result.model
            record["usage"] = result.usage
            record["response"] = result.content
        elif isinstance(result, dict):
            # generate_json returns JsonResult (dict subclass) with .usage.
            record["response"] = json.dumps(dict(result), ensure_ascii=False, default=str)
            if isinstance(result, JsonResult) and result.usage:
                record["usage"] = result.usage
                if result.model and not record.get("model"):
                    record["model"] = result.model
        elif isinstance(result, str):
            record["model"] = ""
            record["response"] = result
        else:
            record["response"] = None

        if self._error:
            record["error"] = self._error

        record.update(self.meta)
        self._records.append(record)
        self.store.append(record)

    # ------------------------------------------------------------------
    # Context manager protocol — always close the record, even on error.
    def __enter__(self) -> "LLMTrace":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None and not self._records:
            # The call blew up before any record() — write a stub so we can
            # still see what the caller tried to do.
            self._error = f"{type(exc).__name__}: {exc}"
            self.store.append({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "stage": self.stage,
                "project": self.project,
                "chapter": self.chapter,
                "started_at": self.started_at.isoformat(timespec="seconds"),
                "error": self._error,
                **self.meta,
                "prompt": [],
                "response": None,
            })
        # Never suppress the caller's exception.
        return False


class _NullTrace:
    """Drop-in no-op for callers without a real TraceStore.

    Lets pipeline components stay simple: ``self.trace.begin(...)`` works
    whether or not a project-scoped TraceStore was injected.
    """

    enabled = False

    def begin(
        self,
        stage: str,
        *,
        project: str = "",
        chapter: int | None = None,
        **meta: Any,
    ) -> "LLMTrace":
        # Return a LLMTrace bound to a disabled store so ``record()`` is
        # equally cheap (early return) and exception-safe.
        return LLMTrace(
            TraceStore(None),
            stage,
            project=project,
            chapter=chapter,
            **meta,
        )


NULL_TRACE = _NullTrace()