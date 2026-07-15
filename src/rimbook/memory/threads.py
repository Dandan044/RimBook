"""Plot-thread ledger — structured foreshadowing / suspense tracking.

Long-form fiction lives and dies by its promises to the reader: foreshadowing
planted in chapter 3 must pay off, suspense raised in chapter 10 must resolve.
Chapter notes alone are too soft for this — over dozens of chapters, threads
silently disappear from every context window and are forgotten.

This module keeps a hard ledger (``state/threads.yaml``): every thread has an
id, a lifecycle status, and a per-chapter update trail. The post-write
pipeline extracts thread deltas from each chapter; the planner injects the
open threads into chapter planning so the LLM actively progresses or resolves
them; the checker sees them too (e.g. to catch a premature reveal).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..project import ProjectPaths
from ..versioning import atomic_write

__all__ = ["PlotThread", "ThreadUpdate", "ThreadStore", "THREAD_TYPES", "THREAD_STATUSES"]

THREAD_TYPES = ("foreshadow", "suspense", "promise")
THREAD_STATUSES = ("open", "progressed", "resolved")


class ThreadUpdate(BaseModel):
    """One chapter's worth of movement on a thread."""

    chapter: int
    note: str = ""


class PlotThread(BaseModel):
    """A single tracked plot thread (foreshadowing / suspense / promise)."""

    id: str
    description: str = ""
    type: str = Field(default="foreshadow", description="foreshadow | suspense | promise")
    planted_chapter: int = 0
    status: str = Field(default="open", description="open | progressed | resolved")
    expected_resolve_chapter: int | None = None
    resolved_chapter: int | None = None
    updates: list[ThreadUpdate] = Field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status != "resolved"


class ThreadStore:
    """Read & write the plot-thread ledger (``state/threads.yaml``)."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.file = paths.threads_file

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------
    def all(self) -> list[PlotThread]:
        if not self.file.exists():
            return []
        try:
            data = yaml.safe_load(self.file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return []
        raw = data.get("threads") if isinstance(data, dict) else None
        out: list[PlotThread] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            try:
                out.append(PlotThread.model_validate(item))
            except Exception:
                continue
        return out

    def save_all(self, threads: list[PlotThread]) -> Path:
        payload = {"threads": [t.model_dump(mode="json") for t in threads]}
        self.file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self.file,
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        )
        return self.file

    def open_threads(self) -> list[PlotThread]:
        return [t for t in self.all() if t.is_open]

    # ------------------------------------------------------------------
    # Merge a chapter's extracted deltas
    # ------------------------------------------------------------------
    def apply_deltas(self, data: dict[str, Any], chapter_number: int) -> dict[str, int]:
        """Merge an LLM thread-extraction payload into the ledger.

        Expects ``{"new_threads": [...], "progressed": [...], "resolved": [...]}``.
        Returns counts of applied changes.
        """
        threads = self.all()
        by_id = {t.id: t for t in threads}
        counts = {"created": 0, "progressed": 0, "resolved": 0}

        for raw in data.get("new_threads") or []:
            if not isinstance(raw, dict):
                continue
            tid = _slug(str(raw.get("id", "")).strip())
            desc = str(raw.get("description", "")).strip()
            if not tid or not desc:
                continue
            note = str(raw.get("note", "")).strip()
            if tid in by_id:
                # LLM re-planted an existing thread — treat as progress.
                t = by_id[tid]
                t.updates.append(ThreadUpdate(chapter=chapter_number, note=note or desc))
                if t.status == "open":
                    t.status = "progressed"
                counts["progressed"] += 1
                continue
            ttype = str(raw.get("type", "foreshadow")).strip().lower()
            if ttype not in THREAD_TYPES:
                ttype = "foreshadow"
            expected = raw.get("expected_resolve_chapter")
            try:
                expected = int(expected) if expected is not None else None
            except (TypeError, ValueError):
                expected = None
            t = PlotThread(
                id=tid,
                description=desc,
                type=ttype,
                planted_chapter=chapter_number,
                status="open",
                expected_resolve_chapter=expected,
                updates=[ThreadUpdate(chapter=chapter_number, note=note or "埋下线索")],
            )
            threads.append(t)
            by_id[tid] = t
            counts["created"] += 1

        for raw in data.get("progressed") or []:
            if not isinstance(raw, dict):
                continue
            tid = _slug(str(raw.get("id", "")).strip())
            t = by_id.get(tid)
            if t is None or not t.is_open:
                continue
            t.updates.append(ThreadUpdate(
                chapter=chapter_number, note=str(raw.get("note", "")).strip(),
            ))
            t.status = "progressed"
            counts["progressed"] += 1

        for raw in data.get("resolved") or []:
            if not isinstance(raw, dict):
                continue
            tid = _slug(str(raw.get("id", "")).strip())
            t = by_id.get(tid)
            if t is None:
                continue
            t.updates.append(ThreadUpdate(
                chapter=chapter_number, note=str(raw.get("note", "")).strip(),
            ))
            t.status = "resolved"
            t.resolved_chapter = chapter_number
            counts["resolved"] += 1

        self.save_all(threads)
        return counts

    # ------------------------------------------------------------------
    # Formatting for prompts
    # ------------------------------------------------------------------
    def format_open_threads(self, *, upto_chapter: int | None = None) -> str:
        """Human/LLM-readable list of unresolved threads for prompt injection."""
        threads = self.open_threads()
        if upto_chapter is not None:
            threads = [t for t in threads if t.planted_chapter <= upto_chapter]
        if not threads:
            return ""
        lines: list[str] = []
        type_labels = {"foreshadow": "伏笔", "suspense": "悬念", "promise": "承诺"}
        for t in threads:
            label = type_labels.get(t.type, t.type)
            line = f"- [{t.id}]（{label}，第{t.planted_chapter}章埋下）{t.description}"
            if t.expected_resolve_chapter:
                line += f"（预计第{t.expected_resolve_chapter}章回收）"
            last = t.updates[-1] if t.updates else None
            if last and last.note and last.chapter != t.planted_chapter:
                line += f"｜最近进展（第{last.chapter}章）：{last.note}"
            lines.append(line)
        return "\n".join(lines)


def _slug(raw: str) -> str:
    """Normalize a thread id to a safe slug (filename-safe, lowercase)."""
    import re

    s = raw.strip().lower()
    s = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", s).strip("_")
    if s and not s.startswith("thread_"):
        s = f"thread_{s}"
    return s
