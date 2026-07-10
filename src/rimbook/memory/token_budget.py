"""Lightweight token estimation and budget allocation for context assembly.

We avoid pulling in a tokenizer (tiktoken / transformers) to keep RimBook
dependency-free for non-OpenAI backends. The estimate is deliberately
conservative — it's a *budgeting* heuristic, not a billing-accurate count:

* CJK characters count ~1.5 chars/token (Chinese packs roughly one token per
  1–2 characters).
* ASCII text counts ~4 chars/token (English).
* A small per-segment overhead is added to account for structural markup.

This is good enough to decide "does this codex entry fit the budget?" without
ever needing to call the API.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "estimate_tokens",
    "truncate_to_chars",
    "BudgetAllocator",
    "BudgetedItem",
]


def estimate_tokens(text: str) -> int:
    """Estimate the token count of *text* using a CJK/ASCII heuristic."""
    if not text:
        return 0
    cjk = 0
    ascii_chars = 0
    for ch in text:
        cp = ord(ch)
        # Common CJK ranges (CJK Unified, extensions A/B, Hiragana, Katakana, Hangul).
        if (
            0x3040 <= cp <= 0x30FF  # Japanese kana
            or 0x3400 <= cp <= 0x9FFF  # CJK + Ext A
            or 0xAC00 <= cp <= 0xD7AF  # Hangul syllables
            or 0xF900 <= cp <= 0xFAFF  # CJK compat ideographs
            or 0xFF00 <= cp <= 0xFFEF  # Fullwidth forms
        ):
            cjk += 1
        else:
            ascii_chars += 1
    # ~1.5 chars/token for CJK, ~4 chars/token for ASCII.
    tokens = cjk / 1.5 + ascii_chars / 4.0
    return int(tokens) + 1  # round up, never under-estimate


def truncate_to_chars(text: str, max_chars: int, *, marker: str = "\n…（已截断）") -> str:
    """Truncate *text* to at most *max_chars* characters, appending a marker."""
    if len(text) <= max_chars:
        return text
    # Leave room for the marker; cut on a paragraph/sentence boundary if close.
    cut = max_chars - len(marker)
    # Try to break at the last newline within the window for cleanliness.
    boundary = text.rfind("\n", 0, cut)
    if boundary > cut * 0.7:
        cut = boundary
    return text[:cut].rstrip() + marker


@dataclass
class BudgetedItem:
    """An item vying for a share of the token budget.

    * ``key`` — unique id for dedup.
    * ``text`` — the content to potentially include.
    * ``priority`` — lower = more important (included first).
    * ``min_chars`` — floor: never truncate below this (drop instead).
    """

    key: str
    text: str
    priority: int = 0
    min_chars: int = 200


class BudgetAllocator:
    """Greedy budget allocator: fill highest-priority items first.

    Usage::

        alloc = BudgetAllocator(budget_tokens=2000)
        for item in sorted(items, key=lambda i: i.priority):
            text = alloc.try_add(item)
            if text is not None:
                emit(text)
    """

    def __init__(self, budget_tokens: int, *, max_chars_per_item: int = 1500) -> None:
        self.budget_tokens = budget_tokens
        self.max_chars_per_item = max_chars_per_item
        self.remaining = budget_tokens
        self._seen: set[str] = set()

    def try_add(self, item: BudgetedItem) -> str | None:
        """Return the (possibly truncated) text if it fits, else None.

        If the full text exceeds the remaining budget *but* fits within
        ``max_chars_per_item`` when truncated down to ``min_chars``, we
        truncate rather than drop — important for high-priority items.
        """
        if item.key in self._seen:
            return None
        if self.remaining <= 0:
            return None

        full_tokens = estimate_tokens(item.text)

        # Fits entirely — best case.
        if full_tokens <= self.remaining:
            self._seen.add(item.key)
            self.remaining -= full_tokens
            return item.text

        # Doesn't fit fully: try truncating to max_chars_per_item first, then
        # down to min_chars. Below min_chars, drop the item entirely.
        for limit in (self.max_chars_per_item, item.min_chars):
            truncated = truncate_to_chars(item.text, limit)
            t_tokens = estimate_tokens(truncated)
            if t_tokens <= self.remaining:
                self._seen.add(item.key)
                self.remaining -= t_tokens
                return truncated

        # Couldn't fit even truncated.
        return None

    @property
    def used_tokens(self) -> int:
        return self.budget_tokens - self.remaining
