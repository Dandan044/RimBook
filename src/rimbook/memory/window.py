"""Sliding window of recent full-prose chapters.

Recent prose keeps the LLM's prose continuity (voice, tense, mood) intact
for the chapter currently being written. Older chapters are *not* loaded in
full — their summaries (see :mod:`summarizer`) stand in for them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..project import ProjectPaths

__all__ = ["SlidingWindow", "WindowedChapter"]


@dataclass
class WindowedChapter:
    number: int
    text: str


class SlidingWindow:
    """Provides the most recent N chapters of full prose for context."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def recent(self, count: int, *, before: int | None = None) -> list[WindowedChapter]:
        """Return up to *count* most recent chapters with prose on disk.

        ``before`` excludes the given chapter number and everything after it
        — used when generating chapter N so we don't leak future text.
        """
        out: list[WindowedChapter] = []
        # Walk chapter draft files in descending order.
        files = sorted(self.paths.drafts_dir.glob("ch*.md"), reverse=True)
        for path in files:
            num = _num(path.stem)
            if num is None:
                continue
            if before is not None and num >= before:
                continue
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            out.append(WindowedChapter(number=num, text=text))
            if len(out) >= count:
                break
        # Return in ascending order for readability.
        out.sort(key=lambda c: c.number)
        return out


def _num(stem: str) -> int | None:
    if stem.startswith("ch"):
        digits = stem[2:]
        if digits.isdigit():
            return int(digits)
    return None
