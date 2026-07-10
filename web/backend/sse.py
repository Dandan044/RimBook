"""Server-Sent Events helpers for streaming LLM progress to the browser."""

from __future__ import annotations

import json
from typing import Any

from sse_starlette.sse import ServerSentEvent


def sse_event(event: str, data: Any = None) -> ServerSentEvent:
    """Create a single SSE event with JSON-encoded data."""
    payload = json.dumps(data, ensure_ascii=False) if data is not None else ""
    return ServerSentEvent(data=payload, event=event)


def sse_progress(message: str) -> ServerSentEvent:
    """Convenience: a progress notification event."""
    return sse_event("progress", {"message": message})


def sse_done(result: Any = None) -> ServerSentEvent:
    """Signal that the stream is complete."""
    return sse_event("done", result)
