"""Shared task registry for long-running operations.

Routes register tasks before starting a long operation (LLM call, file write)
and unregister when done.  This lets the frontend poll for active tasks after
an SSE disconnection or page navigation, showing progress instead of dead UI.

Write tasks also support multi-subscriber fan-out: each SSE client gets its own
queue, so navigating away and reconnecting continues to receive live tokens.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from queue import Queue
from typing import Any

__all__ = ["TaskRegistry", "TaskInfo", "task_registry"]

# Sentinel placed on subscriber queues when the job ends.
_END = ("__end__", None)


@dataclass
class TaskInfo:
    op: str  # "write" | "revise" | "plan_chapter" | "check" | ...
    chapter: int | None = None
    started_at: str = ""
    progress: str = ""
    # Live draft text accumulated during streaming writes (for reconnect).
    stream_text: str = ""
    # True once the background job finished (success or error).
    finished: bool = False
    error: str | None = None
    # Per-client SSE queues (not copied by get()).
    _subscribers: list[Queue] = field(default_factory=list, repr=False)


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

    def register(
        self, project_id: str, op: str, chapter: int | None = None, progress: str = ""
    ) -> None:
        with self._lock:
            self._tasks[self._key(project_id, op, chapter)] = TaskInfo(
                op=op,
                chapter=chapter,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                progress=progress,
            )

    def try_start(
        self, project_id: str, op: str, chapter: int | None = None, progress: str = ""
    ) -> bool:
        """Register a new task if none is active. Returns True if started new.

        Unlike :meth:`begin_or_attach`, does not create a subscriber queue.
        """
        with self._lock:
            key = self._key(project_id, op, chapter)
            t = self._tasks.get(key)
            if t is not None and t.finished:
                del self._tasks[key]
                t = None
            if t is not None:
                return False
            self._tasks[key] = TaskInfo(
                op=op,
                chapter=chapter,
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                progress=progress,
            )
            return True

    def update(
        self, project_id: str, op: str, progress: str, chapter: int | None = None
    ) -> None:
        with self._lock:
            key = self._key(project_id, op, chapter)
            t = self._tasks.get(key)
            if t is None:
                return
            t.progress = progress
            self._broadcast(t, ("progress", progress))

    def append_stream(
        self, project_id: str, op: str, chapter: int | None, text: str
    ) -> None:
        """Append a token delta to the live stream buffer and fan out."""
        if not text:
            return
        with self._lock:
            key = self._key(project_id, op, chapter)
            t = self._tasks.get(key)
            if t is None:
                return
            t.stream_text += text
            n = len(t.stream_text)
            t.progress = f"正在流式输出正文…（已 {n} 字）"
            self._broadcast(t, ("token", text))

    def set_stream(
        self, project_id: str, op: str, chapter: int | None, text: str
    ) -> None:
        with self._lock:
            key = self._key(project_id, op, chapter)
            t = self._tasks.get(key)
            if t is not None:
                t.stream_text = text

    def publish(
        self, project_id: str, op: str, chapter: int | None, kind: str, payload: Any
    ) -> None:
        """Fan-out a named event (draft / enrichment / check / …) to subscribers."""
        with self._lock:
            t = self._tasks.get(self._key(project_id, op, chapter))
            if t is None:
                return
            self._broadcast(t, (kind, payload))

    def subscribe(
        self, project_id: str, op: str, chapter: int | None = None
    ) -> tuple[Queue, str, str, bool] | None:
        """Attach a new SSE subscriber.

        Returns ``(queue, stream_text_snapshot, progress, finished)`` or
        ``None`` if no such task exists.  The snapshot lets reconnecting
        clients catch up before receiving live deltas.
        """
        with self._lock:
            t = self._tasks.get(self._key(project_id, op, chapter))
            if t is None:
                return None
            q: Queue = Queue()
            t._subscribers.append(q)
            finished = t.finished
            if finished:
                # Late subscriber: close immediately after replay.
                q.put(_END)
            return q, t.stream_text, t.progress, finished

    def unsubscribe(
        self, project_id: str, op: str, chapter: int | None, q: Queue
    ) -> None:
        with self._lock:
            t = self._tasks.get(self._key(project_id, op, chapter))
            if t is None:
                return
            try:
                t._subscribers.remove(q)
            except ValueError:
                pass

    def mark_finished(
        self,
        project_id: str,
        op: str,
        chapter: int | None = None,
        *,
        error: str | None = None,
    ) -> None:
        with self._lock:
            key = self._key(project_id, op, chapter)
            t = self._tasks.get(key)
            if t is None:
                return
            t.finished = True
            t.error = error
            if error:
                t.progress = f"失败：{error}"
            elif not t.progress.startswith("完成"):
                t.progress = "完成！"
            # Wake every subscriber so their SSE loops can exit.
            for q in list(t._subscribers):
                q.put(_END)

    def unregister(self, project_id: str, op: str, chapter: int | None = None) -> None:
        with self._lock:
            self._tasks.pop(self._key(project_id, op, chapter), None)

    def get(self, project_id: str, op: str, chapter: int | None = None) -> TaskInfo | None:
        with self._lock:
            t = self._tasks.get(self._key(project_id, op, chapter))
            if t is None:
                return None
            # Return a shallow copy so callers can read without holding the lock.
            return TaskInfo(
                op=t.op,
                chapter=t.chapter,
                started_at=t.started_at,
                progress=t.progress,
                stream_text=t.stream_text,
                finished=t.finished,
                error=t.error,
            )

    def list_for_project(self, project_id: str) -> list[TaskInfo]:
        with self._lock:
            return [
                TaskInfo(
                    op=t.op,
                    chapter=t.chapter,
                    started_at=t.started_at,
                    progress=t.progress,
                    stream_text=t.stream_text,
                    finished=t.finished,
                    error=t.error,
                )
                for key, t in self._tasks.items()
                if key.startswith(f"{project_id}:")
            ]

    def has_active(self, project_id: str, op: str, chapter: int | None = None) -> bool:
        t = self.get(project_id, op, chapter)
        return t is not None and not t.finished

    @staticmethod
    def _broadcast(t: TaskInfo, item: tuple[str, Any]) -> None:
        for q in list(t._subscribers):
            q.put(item)


# Module-level singleton shared across the entire server process.
task_registry = TaskRegistry()
