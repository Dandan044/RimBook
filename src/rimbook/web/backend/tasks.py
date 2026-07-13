"""Shared task registry for long-running operations.

Routes register tasks before starting a long operation (LLM call, file write)
and unregister when done.  This lets the frontend poll for active tasks after
an SSE disconnection or page navigation, showing progress instead of dead UI.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["TaskRegistry", "task_registry"]

@dataclass
class TaskInfo:
    op: str          # "write" | "revise" | "plan_chapter" | "check" | ...
    chapter: int | None = None
    started_at: str = ""
    progress: str = ""


class TaskRegistry:
    """Thread-safe registry of active long-running tasks.

    Keyed by ``"project_id:op:chapter"`` so that writing chapter 3 doesn't
    collide with planning chapter 3.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()

    def _key(self, project_id: str, op: str, chapter: int | None = None) -> str:
        return f"{project_id}:{op}:{chapter or ''}"

    def register(self, project_id: str, op: str, chapter: int | None = None, progress: str = "") -> None:
        with self._lock:
            self._tasks[self._key(project_id, op, chapter)] = TaskInfo(
                op=op, chapter=chapter,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                progress=progress,
            )

    def update(self, project_id: str, op: str, progress: str, chapter: int | None = None) -> None:
        with self._lock:
            key = self._key(project_id, op, chapter)
            if key in self._tasks:
                self._tasks[key].progress = progress

    def unregister(self, project_id: str, op: str, chapter: int | None = None) -> None:
        with self._lock:
            self._tasks.pop(self._key(project_id, op, chapter), None)

    def get(self, project_id: str, op: str, chapter: int | None = None) -> TaskInfo | None:
        with self._lock:
            return self._tasks.get(self._key(project_id, op, chapter))

    def list_for_project(self, project_id: str) -> list[TaskInfo]:
        with self._lock:
            return [
                t for key, t in self._tasks.items()
                if key.startswith(f"{project_id}:")
            ]

    def has_active(self, project_id: str, op: str, chapter: int | None = None) -> bool:
        return self.get(project_id, op, chapter) is not None


# Module-level singleton shared across the entire server process.
task_registry = TaskRegistry()