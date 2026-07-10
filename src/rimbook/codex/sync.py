"""Codex auto-sync — keep codex entries consistent with tracked entity state.

Design principle: :class:`EntityState` (``state/entities/*.yaml``) is the
*single source of truth* for an entity's current, mutable state. The codex
body holds only the *static*, human-authored profile (appearance, backstory,
personality, voice profile, …). This module therefore never rewrites an
entry's body to embed state; it only:

1. Ensures a minimal codex entry exists for any tracked entity that lacks one,
   so the entity is queryable in the codex (and appears in the web UI).
2. Keeps each entry's ``related`` list in sync with the entity's current
   relationships (additive — human edits are preserved).

The previous version appended/overwrote a ``### 当前状态（自动追踪）`` section
inside ``body`` via fragile string slicing. That duplicated EntityState and
broke when users renamed the heading. State now flows exclusively through
EntityState → :class:`ContextAssembler`.
"""

from __future__ import annotations

import logging

from ..codex.store import CodexStore
from ..codex.models import CodexEntry
from ..memory.entity_state import EntityState, EntityStateStore
from ..codex.resolve import guess_type, guess_name

__all__ = ["sync_codex_from_states", "strip_state_section"]

logger = logging.getLogger(__name__)

# The legacy marker that earlier versions wrote into codex bodies. We keep the
# constant here so the migration helper (strip_state_section) and tests can
# reference it without hardcoding the string everywhere.
LEGACY_STATE_MARKER = "### 当前状态（自动追踪）"


def sync_codex_from_states(
    entity_ids: list[str],
    entity_store: EntityStateStore,
    codex_store: CodexStore,
) -> list[str]:
    """Bring the codex in line with tracked entity states.

    For each *entity_id* that has a non-empty :class:`EntityState`:
      * If no codex entry exists, create a minimal placeholder (id/name/type,
        empty body with a hint). The body is intentionally left for a human to
        fill in — auto-tracking concerns state, not biography.
      * If an entry exists, only its ``related`` list is updated (additively)
        from the entity's current relationships. The body is never touched.

    Returns the list of entity_ids that were created or had ``related`` updated.
    """
    touched: list[str] = []

    for eid in entity_ids:
        state = entity_store.get(eid)
        if not _state_nonempty(state):
            continue

        try:
            entry = codex_store.read(eid)
            created = False
        except FileNotFoundError:
            entry = _make_placeholder(eid, state)
            codex_store.write(entry)
            touched.append(eid)
            logger.info("Auto-created codex entry for %s", eid)
            continue

        # Existing entry: sync `related` from current relationships (additive).
        if state.relationships and _sync_related(entry, state):
            codex_store.write(entry)
            touched.append(eid)

    return touched


def strip_state_section(body: str) -> tuple[str, str | None]:
    """Remove a legacy ``### 当前状态（自动追踪）`` section from *body*.

    Returns ``(cleaned_body, extracted_state_text)`` where *extracted_state_text*
    is the removed section's content (without the leading marker line), or
    ``None`` when the body contained no such section. Used by the migration
    command to move embedded state out of codex bodies.
    """
    marker = LEGACY_STATE_MARKER
    idx = body.find(marker)
    if idx == -1:
        return body, None

    before = body[:idx].rstrip()
    # Section ends at the next top-level heading (## or #) or end of body.
    after_start = idx + len(marker)
    next_heading = -1
    for line in body[after_start:].splitlines():
        offset = body.find(line, after_start)
        if line.startswith("## ") or line.startswith("# "):
            next_heading = offset
            break
    if next_heading != -1:
        section = body[idx:next_heading].rstrip()
        after = body[next_heading:]
    else:
        section = body[idx:].rstrip()
        after = ""
    cleaned = (before + "\n\n" + after).strip() if after else before
    return cleaned, section


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------
def _make_placeholder(entity_id: str, state: EntityState) -> CodexEntry:
    """Create a minimal codex entry so the entity is queryable & editable."""
    return CodexEntry(
        id=entity_id,
        name=guess_name(entity_id),
        type=guess_type(entity_id),
        aliases=[],
        tags=["auto-created"],
        related=list(state.relationships.keys()),
        body=_PLACEHOLDER_BODY,
    )


_PLACEHOLDER_BODY = (
    "<!-- 此条目由系统自动创建。请补充以下内容：\n"
    "     1. 将上方的「名称」替换为正确的中文名（如「老赵」而非「lao zhao」）；\n"
    "     2. 在下方填写该实体的静态档案（外貌/背景/性格/语言风格等）。\n"
    "     该实体的「当前状态」（位置、持有物、关系等）由 state/entities/ 自动追踪，\n"
    "     无需在此手写。 -->"
)


def _sync_related(entry: CodexEntry, state: EntityState) -> bool:
    """Add any new relationship targets to entry.related. Returns True if changed."""
    if not state.relationships:
        return False
    existing = set(entry.related)
    changed = False
    for target_id in state.relationships:
        if target_id and target_id not in existing:
            entry.related.append(target_id)
            existing.add(target_id)
            changed = True
    return changed


def _state_nonempty(s: EntityState) -> bool:
    return any([
        s.location,
        s.status,
        s.knowledge,
        s.possessions,
        s.relationships,
        s.last_seen_chapter > 0,
    ])
