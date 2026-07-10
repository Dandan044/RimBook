"""Codex migration helpers — one-time fixes for legacy/inconsistent data.

Two migration operations are provided:

* :func:`migrate_state_sections` — move embedded ``### 当前状态（自动追踪）``
  sections out of codex bodies into :class:`EntityState` files (where they
  belong under the new decoupled model), then strip them from the body.
* :func:`merge_duplicate_entities` — detect and merge fragmented entities
  (e.g. ``char_laozhao`` + ``lao_zhao``), fixing references in chapter
  outlines and entity-state files.

Both are idempotent and return a report of what changed, so the CLI can print
a summary and the user can review before committing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..codex.store import CodexStore
from ..codex.resolve import find_duplicates, merge_entries, DuplicateGroup
from ..codex.sync import strip_state_section, LEGACY_STATE_MARKER
from ..memory.entity_state import EntityState, EntityStateStore
from ..outline.store import OutlineStore

__all__ = [
    "migrate_state_sections",
    "merge_duplicate_entities",
    "MigrationReport",
    "MergeReport",
]

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    """Result of :func:`migrate_state_sections`."""

    scanned: int = 0
    cleaned: int = 0
    state_created: int = 0
    state_updated: int = 0
    details: list[str] = field(default_factory=list)


@dataclass
class MergeReport:
    """Result of :func:`merge_duplicate_entities`."""

    groups_found: int = 0
    entries_removed: int = 0
    outlines_fixed: int = 0
    states_fixed: int = 0
    remap: dict[str, str] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Migration 1: strip embedded state sections from codex bodies
# ----------------------------------------------------------------------
def migrate_state_sections(
    codex_store: CodexStore,
    entity_store: EntityStateStore,
) -> MigrationReport:
    """Move legacy ``### 当前状态`` sections from codex bodies → EntityState.

    For each codex entry whose body contains the legacy marker:
      1. Parse location/status/knowledge/possessions/relationships/last_chapter
         out of the embedded text.
      2. Merge those fields into the entry's EntityState (additive, never
         overwriting a non-empty existing field unless it's empty).
      3. Strip the section from the codex body.

    Idempotent: running twice is a no-op (the marker is gone after the first).
    """
    report = MigrationReport()

    for entry in codex_store.iter_all():
        report.scanned += 1
        if LEGACY_STATE_MARKER not in entry.body:
            continue

        cleaned_body, section_text = strip_state_section(entry.body)
        if section_text is None:
            continue

        parsed = _parse_legacy_state(section_text)
        state = entity_store.get(entry.id)
        changed_state = _merge_parsed_into_state(state, parsed)

        if changed_state:
            entity_store.save(state)
            if any(v for v in _existing_state_signature(entity_store.get(entry.id)).values()):
                report.state_updated += 1
            else:
                report.state_created += 1

        # Always rewrite the body to drop the section.
        entry.body = cleaned_body
        codex_store.write(entry)
        report.cleaned += 1
        report.details.append(f"  {entry.id}: stripped state section → EntityState")

    return report


def _parse_legacy_state(text: str) -> dict:
    """Best-effort parse of a legacy state section into fields.

    The legacy format used Markdown bullet points with Chinese labels, e.g.::

        ### 当前状态（自动追踪）
        - **位置**：医院地下室
        - **状态**：被困
        - **已知信息**：
          - fact one
          - fact two
        - **随身物品**：a, b, c
        - **人际关系**：
          - target_id: 关系
        - **最后出现**：第 2 章
    """
    out: dict = {
        "location": "",
        "status": "",
        "knowledge": [],
        "possessions": [],
        "relationships": {},
        "last_seen_chapter": 0,
    }
    lines = text.splitlines()
    i = 0
    current_list: list[str] | None = None
    current_dict: dict[str, str] | None = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Header lines reset the sub-collector.
        if stripped.startswith("- **位置**"):
            out["location"] = _after_colon(stripped)
            current_list = current_dict = None
        elif stripped.startswith("- **状态**"):
            out["status"] = _after_colon(stripped)
            current_list = current_dict = None
        elif stripped.startswith("- **已知信息**"):
            current_list = out["knowledge"]
            current_dict = None
        elif stripped.startswith("- **随身物品**"):
            items = _after_colon(stripped)
            if items:
                out["possessions"].extend(_split_list(items))
            current_list = out["possessions"]
            current_dict = None
        elif stripped.startswith("- **人际关系**"):
            current_dict = out["relationships"]
            current_list = None
        elif stripped.startswith("- **最后出现**"):
            out["last_seen_chapter"] = _parse_chapter_num(_after_colon(stripped))
            current_list = current_dict = None
        elif stripped.startswith("- ") and current_list is not None:
            current_list.append(stripped[2:].strip())
        elif stripped.startswith("- ") and current_dict is not None:
            k, v = _split_kv(stripped[2:])
            if k:
                current_dict[k] = v
        i += 1
    return out


def _merge_parsed_into_state(state: EntityState, parsed: dict) -> bool:
    """Merge parsed legacy fields into *state* (only fill empty fields). Returns changed."""
    changed = False
    if not state.location and parsed["location"]:
        state.location = parsed["location"]
        changed = True
    if not state.status and parsed["status"]:
        state.status = parsed["status"]
        changed = True
    for k in parsed["knowledge"]:
        if k and k not in state.knowledge:
            state.knowledge.append(k)
            changed = True
    for p in parsed["possessions"]:
        if p and p not in state.possessions:
            state.possessions.append(p)
            changed = True
    for k, v in parsed["relationships"].items():
        if k and k not in state.relationships:
            state.relationships[k] = v
            changed = True
    if parsed["last_seen_chapter"] and parsed["last_seen_chapter"] > state.last_seen_chapter:
        state.last_seen_chapter = parsed["last_seen_chapter"]
        changed = True
    return changed


def _existing_state_signature(state: EntityState) -> dict:
    return {
        "location": state.location,
        "status": state.status,
    }


# ----------------------------------------------------------------------
# Migration 2: merge fragmented duplicate entities
# ----------------------------------------------------------------------
def merge_duplicate_entities(
    codex_store: CodexStore,
    outline_store: OutlineStore,
    entity_store: EntityStateStore,
) -> MergeReport:
    """Detect and merge fragmented entities, fixing all references.

    Workflow:
      1. :func:`find_duplicates` clusters entries by core slug.
      2. Each cluster is merged into its canonical entry via
         :func:`merge_entries`.
      3. The returned id remap is applied to every chapter outline's
         ``entities``/``beats[].entities`` and to entity-state files (renaming
         the merged-away state file into the canonical one).
    """
    report = MergeReport()
    groups = find_duplicates(codex_store)
    report.groups_found = len(groups)
    if not groups:
        return report

    # Build a global remap by merging every group.
    remap: dict[str, str] = {}
    for g in groups:
        result = merge_entries(codex_store, into_id=g.canonical_id, from_ids=g.aliases_ids)
        report.entries_removed += len(result.removed_ids)
        remap.update(result.remap)
        report.details.append(
            f"  merged {result.removed_ids} → {g.canonical_id} ({g.reason})"
        )
    report.remap = remap

    # Fix chapter outline references.
    for ch in outline_store.list_chapters():
        changed = _remap_chapter_entities(ch, remap)
        if changed:
            outline_store.write_chapter(ch)
            report.outlines_fixed += 1

    # Fix entity-state files: rename state of removed ids into canonical.
    for old_id, new_id in remap.items():
        if old_id == new_id:
            continue
        try:
            old_state = entity_store.get(old_id)
            canon_state = entity_store.get(new_id)
            _merge_state(canon_state, old_state)
            entity_store.save(canon_state)
            # Remove the old state file.
            old_path = entity_store._path(old_id)
            if old_path.exists():
                old_path.unlink()
            report.states_fixed += 1
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to merge state %s → %s: %s", old_id, new_id, exc)

    return report


# ----------------------------------------------------------------------
# Migration 3: unstructured body → structured frontmatter (v2)
# ----------------------------------------------------------------------
_REVELATION_PATTERN = re.compile(
    r"\n*---\n### 🤖 第(\d+)章自动揭示\n(.*?)(?=\n---\n### 🤖 第|\n---\n### ⚠️|\n*$)",
    re.DOTALL,
)
_CONTRADICTION_PATTERN = re.compile(
    r"\n*---\n### ⚠️ 待审核矛盾（第(\d+)章）\n(.*?)(?=\n---\n### 🤖 第|\n---\n### ⚠️|\n*$)",
    re.DOTALL,
)


@dataclass
class StructMigrationReport:
    scanned: int = 0
    revelations_extracted: int = 0
    contradictions_extracted: int = 0
    conflicts_skipped: int = 0
    details: list[str] = field(default_factory=list)


def migrate_to_structured(
    codex_store: CodexStore,
) -> StructMigrationReport:
    """Extract legacy markdown sections from body into structured frontmatter.

    Scans every codex entry's body for:
      * ``### 🤖 第N章自动揭示`` → :class:`Revelation` objects.
      * ``### ⚠️ 待审核矛盾（第N章）`` → :class:`Contradiction` objects.

    After extraction the sections are removed from the body. If a structured
    field already has data for the same chapter, the legacy section is
    skipped (idempotent).
    """
    from ..codex.models import Revelation, Contradiction

    report = StructMigrationReport()
    for entry in codex_store.iter_all():
        report.scanned += 1
        body = entry.body
        changed = False

        # ---- revelations ----
        existing_chapters = {r.chapter for r in entry.revelations}
        for m in _REVELATION_PATTERN.finditer(body):
            ch = int(m.group(1))
            content = m.group(2).strip()
            if ch in existing_chapters:
                report.conflicts_skipped += 1
                continue
            entry.revelations.append(Revelation(chapter=ch, content=content))
            report.revelations_extracted += 1
            changed = True

        # ---- contradictions ----
        existing_contra_chapters = {c.chapter for c in entry.contradictions}
        for m in _CONTRADICTION_PATTERN.finditer(body):
            ch = int(m.group(1))
            content = m.group(2).strip()
            if ch in existing_contra_chapters:
                report.conflicts_skipped += 1
                continue
            entry.contradictions.append(Contradiction(
                chapter=ch, description=content,
            ))
            report.contradictions_extracted += 1
            changed = True

        # ---- strip sections from body ----
        if changed:
            # Remove matched sections from body.
            clean = _REVELATION_PATTERN.sub("", body)
            clean = _CONTRADICTION_PATTERN.sub("", clean)
            entry.body = clean.strip() + "\n"
            codex_store.write(entry)
            report.details.append(
                f"  {entry.id}: +{report.revelations_extracted} revelations, "
                f"+{report.contradictions_extracted} contradictions"
            )

    return report


def _remap_chapter_entities(ch, remap: dict[str, str]) -> bool:
    """Rewrite a chapter outline's entity ids in-place. Returns True if changed."""
    changed = False

    def _fix_list(items: list[str]) -> None:
        nonlocal changed
        new = []
        seen: set[str] = set()
        for eid in items:
            mapped = remap.get(eid, eid)
            if mapped not in seen:
                new.append(mapped)
                seen.add(mapped)
            if mapped != eid:
                changed = True
        items[:] = new

    _fix_list(ch.entities)
    for beat in ch.beats:
        _fix_list(beat.entities)
    return changed


def _merge_state(target: EntityState, source: EntityState) -> None:
    """Merge *source* state into *target* (additive for lists/dicts)."""
    if source.location and not target.location:
        target.location = source.location
    if source.status and not target.status:
        target.status = source.status
    for k in source.knowledge:
        if k not in target.knowledge:
            target.knowledge.append(k)
    for p in source.possessions:
        if p not in target.possessions:
            target.possessions.append(p)
    for k, v in source.relationships.items():
        if k not in target.relationships:
            target.relationships[k] = v
    target.last_seen_chapter = max(target.last_seen_chapter, source.last_seen_chapter)


# ----------------------------------------------------------------------
# parsing helpers
# ----------------------------------------------------------------------
def _after_colon(line: str) -> str:
    """Return the substring after a '**label**：' prefix, stripped."""
    # Match "  - **label**：value" → value.  Tolerate ：(fullwidth) and :(ascii).
    m = re.search(r"\*\*.+?\*\*\s*[:：]\s*(.*)$", line)
    return m.group(1).strip() if m else ""


def _split_list(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,，、]", s) if x.strip()]


def _split_kv(s: str) -> tuple[str, str]:
    # "target_id: 关系" or "target_id：关系"
    for sep in (":", "："):
        if sep in s:
            k, _, v = s.partition(sep)
            return k.strip(), v.strip()
    return s.strip(), ""


def _parse_chapter_num(s: str) -> int:
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else 0
