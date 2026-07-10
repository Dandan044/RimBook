"""Entity ID resolution, disambiguation, and dedup utilities.

The single most common source of inconsistency in RimBook is *entity
fragmentation*: the planner's LLM freely invents entity ids that don't match
existing codex entries, so one character ends up as ``lao_zhao`` in chapter 1
and ``char_laozhao`` in chapter 2 — two separate tracking files, two separate
codex bodies, state split across both.

This module provides:

* :func:`guess_type` / :func:`guess_name` — heuristic derivation of a codex
  type / display name from a slug (moved here from ``sync.py`` so both
  auto-creation and resolution share one source of truth).
* :func:`resolve_entity_id` — map an LLM-produced id to a canonical codex id,
  using exact match, alias/name match, and ``new:``-prefix conventions.
* :func:`resolve_entity_ids` — batch-resolve with a lookup table.
* :func:`find_duplicates` — detect likely-fragmented entities by name/alias
  overlap.
* :func:`merge_entries` — merge one codex entry into another (combining
  aliases, tags, related, and body) and return the id remapping so callers can
  fix references elsewhere.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..codex.models import CodexEntry, ENTITY_TYPE_PLURALS, VALID_TYPES
from ..codex.store import CodexStore

__all__ = [
    "guess_type",
    "guess_name",
    "slugify",
    "resolve_entity_id",
    "resolve_entity_ids",
    "ResolvedId",
    "find_duplicates",
    "DuplicateGroup",
    "merge_entries",
    "MergeResult",
]

logger = logging.getLogger(__name__)

# Prefix → codex type. Shared by auto-creation and resolution so the two never
# disagree about what a prefix means.
_PREFIX_MAP = {
    "char_": "character",
    "loc_": "location",
    "item_": "item",
    "faction_": "faction",
    "set_": "worldbuilding",
    "evt_": "timeline",
}

# Prefixes that are purely structural (type hints) and carry no meaning in a
# display name. Used by guess_name() and fuzzy matching.
_TYPE_PREFIXES = tuple(_PREFIX_MAP.keys())

# Marker an LLM may prepend to signal a deliberately new entity (so the
# resolver doesn't try to force-match it to an existing one).
NEW_ENTITY_PREFIX = "new:"


# ----------------------------------------------------------------------
# Slug / type / name derivation
# ----------------------------------------------------------------------
def slugify(text: str) -> str:
    """Normalize free text into a slug-safe id segment (lowercase, underscores)."""
    text = text.strip().lower()
    # CJK characters are kept as-is; whitespace/punctuation → underscore.
    text = re.sub(r"[\s\-/.,;:!?'\"()]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "entity"


def guess_type(entity_id: str) -> str:
    """Guess the codex type from an entity_id prefix, defaulting to character."""
    for prefix, codex_type in _PREFIX_MAP.items():
        if entity_id.startswith(prefix):
            return codex_type
    return "character"


def guess_name(entity_id: str) -> str:
    """Derive a human-readable name from an entity_id slug.

    Strips a type prefix (``char_``, ``loc_``, …), then turns underscores into
    spaces. The result is left as-is (no title-casing) because RimBook targets
    Chinese-language fiction where English title-case names like "Lao Zhao"
    look unnatural. The user should replace the guessed name with the proper
    Chinese name (e.g. "老赵") when editing the codex entry.
    """
    name = entity_id
    for prefix in _TYPE_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = name.replace("_", " ").strip()
    return name or entity_id


# ----------------------------------------------------------------------
# ID resolution
# ----------------------------------------------------------------------
@dataclass
class ResolvedId:
    """Outcome of resolving one raw id against the codex.

    * ``raw_id`` — the original id string provided by the LLM.
    * ``canonical_id`` — the id to use (existing entry id, or a cleaned new id).
    * ``is_existing`` — True if matched to an existing codex entry.
    * ``is_new`` — True if the LLM explicitly marked this as new (``new:``).
    * ``match_reason`` — how the match was found, for logging/diagnostics.
    """

    raw_id: str = ""
    canonical_id: str = ""
    is_existing: bool = False
    is_new: bool = False
    match_reason: str = ""


def resolve_entity_id(raw_id: str, codex_store: CodexStore) -> ResolvedId:
    """Map an LLM-produced entity id to a canonical codex id.

    Resolution order:
      1. Explicit ``new:`` prefix → confirmed new entity, prefix stripped.
      2. Exact id match in codex → that id.
      3. Exact name/alias match (case-insensitive) → the entry's id.
      4. Prefix-stripped fuzzy match (e.g. ``char_laozhao`` ↔ ``lao_zhao``)
         on the *core* slug → existing id, with a warning logged.
      5. No match → treated as a new entity (kept as-is, cleaned).

    This is deliberately conservative: it prefers reusing existing entries and
    only ever returns a *different* string when there's a concrete match.
    """
    raw = (raw_id or "").strip()
    if not raw:
        return ResolvedId(raw_id=raw, canonical_id="", match_reason="empty")

    # 1. Explicit new-entity marker.
    if raw.startswith(NEW_ENTITY_PREFIX):
        clean = slugify(raw[len(NEW_ENTITY_PREFIX):])
        return ResolvedId(
            raw_id=raw,
            canonical_id=_apply_prefix(clean, raw[len(NEW_ENTITY_PREFIX):]),
            is_new=True,
            match_reason="explicit new:",
        )

    # Build lookup tables once.
    all_entries = list(codex_store.iter_all())
    by_id = {e.id: e for e in all_entries}

    # 2. Exact id match.
    if raw in by_id:
        return ResolvedId(
            raw_id=raw, canonical_id=raw, is_existing=True, match_reason="exact id"
        )

    # 3. Name / alias match (case-insensitive).
    target = raw.lower()
    for entry in all_entries:
        candidates = [entry.name.lower(), *(a.lower() for a in entry.aliases)]
        # Also try the display-name derived from the entry's own id.
        candidates.append(guess_name(entry.id).lower())
        if target in candidates:
            return ResolvedId(
                raw_id=raw,
                canonical_id=entry.id,
                is_existing=True,
                match_reason=f"name/alias match: {entry.name}",
            )
    # Also match the *guessed name* of the raw id against entry names.
    raw_name = guess_name(raw).lower()
    if raw_name and raw_name != target:
        for entry in all_entries:
            candidates = {entry.name.lower(), *(a.lower() for a in entry.aliases)}
            if raw_name in candidates:
                return ResolvedId(
                    raw_id=raw,
                    canonical_id=entry.id,
                    is_existing=True,
                    match_reason=f"guessed-name match: {entry.name}",
                )

    # 4. Prefix-stripped core-slug fuzzy match.
    raw_core = _core_slug(raw)
    if raw_core:
        for entry in all_entries:
            entry_core = _core_slug(entry.id)
            if entry_core and entry_core == raw_core:
                logger.warning(
                    "Fuzzy id match: %r → %r (core slug %r)", raw, entry.id, raw_core
                )
                return ResolvedId(
                    raw_id=raw,
                    canonical_id=entry.id,
                    is_existing=True,
                    match_reason=f"fuzzy core-slug match with {entry.id}",
                )

    # 5. No match — keep as a new id, but clean/slugify it.
    return ResolvedId(
        raw_id=raw, canonical_id=slugify(raw), is_new=True, match_reason="no match (new)"
    )


def resolve_entity_ids(
    raw_ids: list[str], codex_store: CodexStore
) -> tuple[list[str], list[ResolvedId]]:
    """Resolve a batch of ids; returns (canonical_ids, resolution_log).

    Deduplicates while preserving first-seen order.
    """
    seen: set[str] = set()
    canonical: list[str] = []
    log: list[ResolvedId] = []
    for raw in raw_ids:
        r = resolve_entity_id(raw, codex_store)
        if not r.canonical_id or r.canonical_id in seen:
            continue
        seen.add(r.canonical_id)
        canonical.append(r.canonical_id)
        log.append(r)
    return canonical, log


# ----------------------------------------------------------------------
# Duplicate detection & merging
# ----------------------------------------------------------------------
@dataclass
class DuplicateGroup:
    """A cluster of entry ids that likely refer to the same entity."""

    canonical_id: str
    aliases_ids: list[str] = field(default_factory=list)
    reason: str = ""


def find_duplicates(codex_store: CodexStore) -> list[DuplicateGroup]:
    """Detect likely-duplicate entries by core-slug and name overlap.

    Two entries are considered duplicates when their *core slugs* (prefix
    stripped, lowercased) are equal — e.g. ``char_laozhao`` and ``lao_zhao``
    both reduce to ``laozhao``.
    """
    entries = list(codex_store.iter_all())
    by_core: dict[str, list[CodexEntry]] = {}
    for e in entries:
        core = _core_slug(e.id)
        if core:
            by_core.setdefault(core, []).append(e)

    groups: list[DuplicateGroup] = []
    for core, group in by_core.items():
        if len(group) < 2:
            continue
        # Pick the richest entry (longest body, most aliases) as canonical.
        canonical = max(group, key=lambda e: (len(e.body), len(e.aliases)))
        others = [e.id for e in group if e.id != canonical.id]
        if others:
            groups.append(
                DuplicateGroup(
                    canonical_id=canonical.id,
                    aliases_ids=others,
                    reason=f"shared core slug: {core}",
                )
            )
    return groups


@dataclass
class MergeResult:
    """Outcome of merging entries. Carries the id remap for fixing references."""

    canonical_id: str
    removed_ids: list[str] = field(default_factory=list)
    remap: dict[str, str] = field(default_factory=dict)


def merge_entries(
    codex_store: CodexStore,
    *,
    into_id: str,
    from_ids: list[str],
) -> MergeResult:
    """Merge *from_ids* into the *into_id* codex entry, then delete the sources.

    Combines aliases, tags, related (union), and bodies (concatenated with a
    separator). Returns a :class:`MergeResult` whose ``remap`` maps each removed
    id → ``into_id`` so callers can fix outline/state references.

    No heuristic auto-merging of *state* happens here — that is the caller's
    responsibility (see :func:`merge_entity_states` in the migration helpers),
    because state merging can lose information and should be explicit.
    """
    try:
        target = codex_store.read(into_id)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Cannot merge into missing entry {into_id!r}") from exc

    removed: list[str] = []
    remap: dict[str, str] = {}

    for fid in from_ids:
        if fid == into_id:
            continue
        try:
            source = codex_store.read(fid)
        except FileNotFoundError:
            logger.warning("Merge source %r not found; skipping", fid)
            continue

        # Union fields.
        target.aliases = _union(target.aliases, [source.name, *source.aliases])
        target.tags = _union(target.tags, source.tags)
        target.related = _union(target.related, source.related)

        # Concatenate bodies if the source has non-trivial content.
        src_body = source.body.strip()
        if src_body:
            sep = "\n\n---\n（合并自 %s）\n" % fid
            target.body = target.body.rstrip() + sep + src_body

        codex_store.delete(fid)
        removed.append(fid)
        remap[fid] = into_id

    codex_store.write(target)
    return MergeResult(canonical_id=into_id, removed_ids=removed, remap=remap)


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------
def _core_slug(entity_id: str) -> str:
    """Strip a type prefix and normalize to a lowercase core slug.

    ``char_laozhao`` → ``laozhao``, ``lao_zhao`` → ``laozhao`` (underscores
    removed) so the two compare equal.
    """
    s = entity_id.strip().lower()
    for prefix in _TYPE_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    # Remove underscores so ``lao_zhao`` == ``laozhao``.
    return s.replace("_", "")


def _apply_prefix(slug: str, original: str) -> str:
    """If the original had a recognized type prefix but the slug lost it, re-add it.

    ``slugify`` preserves underscores and ASCII characters, so a slug derived
    from ``char_newguy`` is already ``char_newguy`` — no double-prefix needed.
    Only add a prefix when the original had one but the slug doesn't start
    with it (e.g. original ``char_老赵`` → slug ``老赵`` → ``char_老赵``).
    """
    for prefix in _TYPE_PREFIXES:
        if original.startswith(prefix) and not slug.startswith(prefix):
            return prefix + slug
    return slug


def _union(base: list[str], extra: list[str]) -> list[str]:
    out = list(base)
    seen = {x.lower() for x in base}
    for x in extra:
        if x and x.lower() not in seen:
            out.append(x)
            seen.add(x.lower())
    return out


# Re-export the type prefixes for callers that need them.
ENTITY_TYPE_PLURALS  # noqa: B018 — keep import live for re-export scenarios
VALID_TYPES  # noqa: B018
