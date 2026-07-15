"""Post-write pipeline — LLM-driven codex enrichment after each chapter.

After a chapter is written (or revised), this module orchestrates a
comprehensive LLM-driven post-processing pass that:

1. Extracts entity-state deltas (existing :class:`Summarizer`).
2. **Discovers new entities** in the chapter text that aren't yet in the codex,
   and generates full archival profiles for them.
3. **Enriches existing entities** by identifying new information revealed in
   this chapter and appending it to their codex body.
4. **Flags contradictions** between the chapter and existing codex entries,
   marking them for human review.

The key design difference from the old ``sync_codex_from_states`` approach:
previously, new entities got empty placeholders. Now the LLM writes a real
profile based on what the chapter actually reveals.

Smart merge policy:
   * New entities → full LLM-generated body written as the codex entry.
   * Existing entities → new information appended as a ``🤖 第N章自动揭示``
     section, never overwriting human-authored content.
   * Contradictions → appended as a ``⚠️ 待审核矛盾`` section with the
     conflicting evidence quoted for human review.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..codex import CodexEntry, CodexStore, sync_codex_from_states
from ..codex.models import Revelation, Contradiction, Relationship
from ..codex.resolve import resolve_entity_id, slugify
from ..config import GenerationConfig
from ..llm import LLMClient, Prompts
from ..llm.trace import NULL_TRACE, TraceStore
from ..memory.summarizer import Summarizer
from ..memory.entity_state import EntityStateStore
from ..memory.threads import ThreadStore
from ..outline import ChapterOutline

__all__ = ["PostWritePipeline", "EnrichResult", "EnrichmentChange"]

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentChange:
    """A single change applied during enrichment."""

    entity_id: str
    action: str  # "created", "updated", "contradiction"
    detail: str = ""


@dataclass
class EnrichResult:
    """Outcome of a post-write enrichment pass."""

    chapter_number: int
    entities_created: list[EnrichmentChange] = field(default_factory=list)
    entities_updated: list[EnrichmentChange] = field(default_factory=list)
    contradictions: list[EnrichmentChange] = field(default_factory=list)
    summary: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    # Plot-thread ledger changes: {"created": n, "progressed": n, "resolved": n}.
    thread_changes: dict[str, int] = field(default_factory=dict)


class PostWritePipeline:
    """LLM-driven post-write processing: state + codex enrichment."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        prompts: Prompts,
        codex: CodexStore,
        entity_state: EntityStateStore,
        summarizer: Summarizer,
        generation: GenerationConfig,
        version_manager=None,
        trace: TraceStore | None = None,
        project_name: str = "",
    ) -> None:
        self.llm = llm
        self.prompts = prompts
        self.codex = codex
        self.entity_state = entity_state
        self.summarizer = summarizer
        self.generation = generation
        self.version_manager = version_manager
        self.trace = trace if trace is not None else NULL_TRACE
        self.project_name = project_name
        # Plot-thread ledger lives next to entity state (state/threads.yaml).
        self.threads = ThreadStore(entity_state.paths)

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    def run(
        self,
        number: int,
        draft_text: str,
        chapter: ChapterOutline,
        *,
        enrich: bool = True,
        light: bool = False,
    ) -> EnrichResult:
        """Execute the full post-write pipeline for one chapter.

        Steps:
          1. Summarize (best-effort).
          2. Extract & apply entity state deltas (best-effort).
          3. Extract & merge plot-thread deltas (best-effort).
          4. LLM-driven codex enrichment (if *enrich* is True).
          5. Sync codex ``related`` fields.
          6. Hierarchical memory maintenance: story-so-far + volume recaps.
          7. Incremental vector-index update (when enabled).

        *light* mode (used after targeted fixes) refreshes only the summary
        and entity state — the thread ledger, hierarchical memory, and vector
        index were already updated by the original write of this chapter.

        If a severe error occurs that corrupts the pipeline state and a
        version_manager is available, the caller's pre-write checkpoint
        serves as the rollback point. Individual step failures are logged
        and skipped (best-effort), preserving partial progress.
        """
        result = EnrichResult(chapter_number=number)

        # 1. Summarize.
        try:
            self.summarizer.summarize(number, draft_text)
        except Exception as exc:  # pragma: no cover
            logger.warning("Summarization failed for ch%d: %s", number, exc)

        # 2. Entity state deltas.
        entity_ids = chapter.all_entities()
        # Defensive: strip any ``new:`` prefix that survived from a pre-fix
        # planner run (the colon is illegal in a Windows filename, and the
        # prefix is meaningless after the entity was created).
        entity_ids = [_strip_new_prefix(eid) for eid in entity_ids]
        try:
            if entity_ids:
                deltas = self.summarizer.extract_entity_deltas(
                    number, draft_text, entity_ids, codex=self.codex,
                )
                Summarizer.apply_deltas(deltas, self.entity_state, number)
        except Exception as exc:  # pragma: no cover
            logger.warning("State extraction failed for ch%d: %s", number, exc)

        # 3. Plot-thread ledger deltas.
        if self.generation.track_threads and not light:
            try:
                result.thread_changes = self.extract_threads(number, draft_text)
            except Exception as exc:  # pragma: no cover
                logger.warning("Thread extraction failed for ch%d: %s", number, exc)

        # 4. LLM-driven codex enrichment.
        if enrich and entity_ids:
            try:
                enrich_result = self.enrich_codex(number, draft_text, entity_ids)
                thread_changes = result.thread_changes
                result = self._apply_enrichment(enrich_result, number)
                result.thread_changes = thread_changes
            except Exception as exc:  # pragma: no cover
                logger.warning("Enrichment failed for ch%d: %s", number, exc)

        # 5. Sync codex related fields (no placeholders — enrichment handles new entities).
        try:
            if entity_ids:
                sync_codex_from_states(
                    entity_ids,
                    self.entity_state,
                    self.codex,
                    create_placeholders=not enrich,
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Codex sync failed for ch%d: %s", number, exc)

        # 6. Hierarchical memory: rolling story-so-far + completed-volume recaps.
        if not light:
            try:
                self._maintain_hierarchical_memory(number, chapter)
            except Exception as exc:  # pragma: no cover
                logger.warning("Hierarchical memory update failed for ch%d: %s", number, exc)

        # 7. Incremental vector-index update.
        if self.generation.use_vector_retrieval and not light:
            try:
                self._update_vector_index(number, entity_ids)
            except Exception as exc:  # pragma: no cover
                logger.warning("Vector index update failed for ch%d: %s", number, exc)

        return result

    # ------------------------------------------------------------------
    # Plot-thread extraction
    # ------------------------------------------------------------------
    def extract_threads(self, chapter_number: int, chapter_text: str) -> dict[str, int]:
        """Ask the LLM which plot threads this chapter planted/progressed/resolved,
        then merge the deltas into the ledger. Returns applied-change counts."""
        open_blob = self.threads.format_open_threads() or "（暂无未回收的线索）"
        messages = self.llm.as_chat(
            system=self.prompts.thread_extract_system,
            user=self.prompts.thread_extract_user.format(
                chapter_number=chapter_number,
                chapter_text=chapter_text[:16384],
                open_threads=open_blob,
            ),
        )
        with self.trace.begin(
            "threads", project=self.project_name, chapter=chapter_number
        ) as t:
            data = self.llm.generate_json(
                messages,
                model=self.llm.config.effective_check_model,
                temperature=0.0,
            )
            t.record(messages, data, model=self.llm.config.effective_check_model)
        counts = self.threads.apply_deltas(data, chapter_number)
        if any(counts.values()):
            logger.info(
                "Threads ch%d: %d created, %d progressed, %d resolved",
                chapter_number, counts["created"], counts["progressed"], counts["resolved"],
            )
        return counts

    # ------------------------------------------------------------------
    # Hierarchical memory maintenance
    # ------------------------------------------------------------------
    def _maintain_hierarchical_memory(self, number: int, chapter: ChapterOutline) -> None:
        """Keep the medium/coarse memory layers fresh as chapters land.

        * Story-so-far: refreshed every ``story_so_far_every`` chapters.
        * Volume recaps: when the current chapter belongs to volume V, any
          earlier volume with chapter summaries but no recap is considered
          complete and gets one generated (lazily, once).
        """
        outline = self.summarizer.outline
        gen = self.generation

        every = gen.story_so_far_every
        if every > 0:
            _, prev_upto = outline.read_story_so_far()
            if number >= prev_upto + every:
                self.summarizer.update_story_so_far(number)

        if gen.auto_volume_recap and chapter.volume:
            for vol in outline.list_volumes():
                if vol.number >= chapter.volume or vol.recap.strip():
                    continue
                has_summaries = any(
                    c.volume == vol.number and c.summary.strip()
                    for c in outline.list_chapters()
                )
                if has_summaries:
                    logger.info("Generating recap for completed volume %d", vol.number)
                    self.summarizer.summarize_volume(vol.number)

    # ------------------------------------------------------------------
    # Incremental vector-index update
    # ------------------------------------------------------------------
    def _update_vector_index(self, number: int, entity_ids: list[str]) -> None:
        """Upsert this chapter's summary + touched codex entries into the index."""
        from ..retrieval import VectorIndexer

        outline = self.summarizer.outline
        indexer = VectorIndexer(self.entity_state.paths, self.llm)
        ch = outline.read_chapter(number)
        if ch is not None and ch.summary.strip():
            indexer.update_summary(number, ch.title, ch.summary.strip())
        for eid in entity_ids:
            try:
                entry = self.codex.read(eid)
            except Exception:
                continue
            indexer.update_codex_entry(entry)

    # ------------------------------------------------------------------
    # LLM enrichment call
    # ------------------------------------------------------------------
    def enrich_codex(
        self,
        chapter_number: int,
        chapter_text: str,
        entity_ids: list[str],
    ) -> dict[str, Any]:
        """Call the LLM to discover new entities and enrich existing profiles.

        Returns the parsed JSON dict with ``new_entities``, ``updates``, and
        ``summary``. Raises ``ValueError`` if the LLM response can't be parsed.
        """
# Build the "existing codex" context block.
        existing_entries = self.codex.get_many(entity_ids)
        existing_text = _format_existing_codex(existing_entries, entity_ids)

        # Build the "planned-new entities" block: ids that the chapter planner
        # already assigned (in chXXX outline entities) but that don't yet have
        # a codex entry. We surface them so the enricher prefers those exact
        # ids when filling in profiles — otherwise it would freely rename the
        # same concept (e.g. ``faction_iron_hand_gang`` → ``faction_iron_fist_gang``),
        # producing the semantic fragmentation we see in the "测试" project.
        planned_new_ids: list[str] = []
        for eid in entity_ids:
            try:
                self.codex.read(eid)
            except Exception:
                planned_new_ids.append(eid)
        planned_block = _format_planned_new(planned_new_ids)

        messages = self.llm.as_chat(
            system=self.prompts.codex_enrich_system,
            user=self.prompts.codex_enrich_user.format(
                chapter_number=chapter_number,
                chapter_text=chapter_text[:16384],  # safety cap
                existing_codex=existing_text,
                planned_new_block=planned_block,
            ),
        )
        with self.trace.begin(
            "enricher", project=self.project_name, chapter=chapter_number
        ) as t:
            gen = self.llm.generate_json(
                messages,
                model=self.llm.config.effective_check_model,
                temperature=0.2,
            )
            t.record(messages, gen, model=self.llm.config.effective_check_model)
        # Attach usage for diagnostics.
        return gen  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Apply enrichment
    # ------------------------------------------------------------------
    def _apply_enrichment(
        self, data: dict[str, Any], chapter_number: int
    ) -> EnrichResult:
        """Persist the LLM's enrichment output to the codex."""
        result = EnrichResult(
            chapter_number=chapter_number,
            summary=str(data.get("summary", "")),
        )

        # --- New entities ---
        for raw in data.get("new_entities") or []:
            if not isinstance(raw, dict):
                continue
            eid = str(raw.get("id", "")).strip()
            if not eid:
                continue
            # Ensure slug format and proper type prefix.
            eid = _normalize_entity_id(eid, str(raw.get("type", "character")))

            # Defensive dedup: even when the planner already normalizes ids,
            # the enrichment LLM can still hallucinate an existing entity under
            # a different id (e.g. ``char_linyuan`` for the existing
            # ``char_lin_yuan``). resolve_entity_id covers exact / alias /
            # name / fuzzy core-slug matches, so a fragmented entry is never
            # created when the entity already exists. On match, we fold the
            # new info (aliases/tags/body/revelations) into the existing entry
            # instead of writing a second file.
            resolved = resolve_entity_id(eid, self.codex)
            if resolved.is_existing:
                canonical = resolved.canonical_id
                logger.warning(
                    "Enrich: new entity %s matched existing %s (%s) — merging "
                    "instead of creating a duplicate",
                    eid, canonical, resolved.match_reason,
                )
                entry = self.codex.read(canonical)
                _merge_into_entry(entry, raw, chapter_number=chapter_number)
                _apply_revelations_and_contradictions(
                    entry, raw, chapter_number, result, change_id=canonical,
                )
                self.codex.write(entry)
                continue

            entry = CodexEntry(
                id=eid,
                name=str(raw.get("name", eid)).strip() or eid,
                type=_valid_type(raw.get("type", "character")),
                aliases=[str(a).strip() for a in (raw.get("aliases") or []) if a],
                tags=[str(t).strip() for t in (raw.get("tags") or []) if t],
                related=[],
                body=str(raw.get("body", "")).strip(),
            )
            # Apply any LLM-provided revelations/contradictions on create.
            _apply_revelations_and_contradictions(
                entry, raw, chapter_number, result, change_id=eid,
            )
            # First appearance MUST have an initializing revelation.
            _ensure_initial_revelation(entry, chapter_number, raw)
            self.codex.write(entry)
            result.entities_created.append(
                EnrichmentChange(
                    entity_id=eid,
                    action="created",
                    detail=f"新建实体：{entry.name} [{entry.type}]",
                )
            )
            logger.info("Enrich: created codex entry %s (%s)", eid, entry.name)

        # --- Updates to existing entities ---
        for raw in data.get("updates") or []:
            if not isinstance(raw, dict):
                continue
            eid = str(raw.get("id", "")).strip()
            if not eid:
                continue
            # Resolve drifted ids to canonical before read(); otherwise an
            # update targeting ``char_linyuan`` would be silently skipped
            # because exact read() can't find it under that form.
            resolved = resolve_entity_id(eid, self.codex)
            target_id = resolved.canonical_id if resolved.is_existing else eid
            if resolved.is_existing and target_id != eid:
                logger.warning(
                    "Enrich: update target %s resolved to existing %s (%s)",
                    eid, target_id, resolved.match_reason,
                )
            try:
                entry = self.codex.read(target_id)
            except Exception:
                logger.warning("Enrich: update target %s not found, skipping", eid)
                continue

            # Structured revelations + contradictions — shared helper so the
            # merge-path (new entity matched an existing one) and the regular
            # update-path stay identical.
            changed = _apply_revelations_and_contradictions(
                entry, raw, chapter_number, result, change_id=target_id,
            )
            if changed:
                self.codex.write(entry)

        return result


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _apply_revelations_and_contradictions(
    entry: CodexEntry,
    raw: dict[str, Any],
    chapter_number: int,
    result: EnrichResult,
    *,
    change_id: str,
) -> bool:
    """Append structured ``revelations`` and ``contradictions`` from *raw* into
    *entry* in place, recording :class:`EnrichmentChange`s into *result*.

    Returns True if *entry* was mutated (caller should ``codex.write`` it).
    The ``change_id`` is the canonical entity id used for the change records
    (the existing entry id, or the resolved one after a merge) — it may differ
    from ``raw["id"]`` when the LLM used a drifted id.
    """
    changed = False

    # Structured revelations (v2).
    revs = raw.get("revelations") or []
    if isinstance(revs, list):
        for rev in revs:
            if not isinstance(rev, dict):
                continue
            content = str(rev.get("content", "")).strip()
            if not content:
                continue
            entry.revelations.append(Revelation(
                chapter=chapter_number,
                content=content,
                source=str(rev.get("source", "")).strip(),
            ))
            result.entities_updated.append(
                EnrichmentChange(
                    entity_id=change_id, action="updated",
                    detail=f"追加发现：{entry.name}",
                )
            )
            changed = True
        if changed:
            logger.info(
                "Enrich: added %d revelation(s) to %s", len(revs), change_id,
            )

    # Structured contradictions (v2).
    contras = raw.get("contradictions") or []
    if isinstance(contras, list):
        for c in contras:
            if not isinstance(c, dict):
                continue
            desc = str(c.get("description", "")).strip()
            if not desc:
                continue
            entry.contradictions.append(Contradiction(
                chapter=chapter_number,
                description=desc,
                evidence=str(c.get("evidence", "")).strip(),
            ))
            result.contradictions.append(
                EnrichmentChange(
                    entity_id=change_id, action="contradiction",
                    detail=f"1 处矛盾：{desc[:40]}",
                )
            )
            changed = True
        if contras:
            logger.warning(
                "Enrich: %d contradiction(s) flagged for %s", len(contras), change_id,
            )

    return changed


def _ensure_initial_revelation(
    entry: CodexEntry,
    chapter_number: int,
    raw: dict[str, Any],
) -> None:
    """Guarantee a newly created entry has at least one revelation for *chapter*.

    The discovery timeline is the chronological record of how an entity entered
    the story.  First appearance must always leave a footprint — even when the
    LLM only filled ``body`` and omitted ``revelations``.
    """
    if any(r.chapter == chapter_number for r in entry.revelations):
        return

    # Prefer an explicit revelation from the payload (already applied above);
    # otherwise synthesise a concise intro from body / name.
    content = ""
    revs = raw.get("revelations") or []
    if isinstance(revs, list):
        for rev in revs:
            if isinstance(rev, dict):
                content = str(rev.get("content", "")).strip()
                if content:
                    break
    if not content:
        body = (entry.body or "").strip()
        if body:
            # First non-empty paragraph, capped.
            para = next(
                (ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")),
                body,
            )
            content = para[:200] + ("…" if len(para) > 200 else "")
        else:
            content = f"第{chapter_number}章首次出现：{entry.name}"

    source = ""
    if isinstance(revs, list):
        for rev in revs:
            if isinstance(rev, dict) and str(rev.get("source", "")).strip():
                source = str(rev.get("source", "")).strip()
                break

    entry.revelations.append(Revelation(
        chapter=chapter_number,
        content=content,
        source=source,
    ))
    logger.info(
        "Enrich: added initial revelation for new entity %s (ch%d)",
        entry.id, chapter_number,
    )


def _merge_into_entry(
    entry: CodexEntry,
    raw: dict[str, Any],
    *,
    chapter_number: int,
) -> None:
    """Fold a 'new entity' payload that actually matched an existing entry
    into *entry* in place. Aliases, tags, related ids and body fragments are
    merged (set-union style, no overwrites) so the existing profile absorbs the
    LLM-proposed duplicate rather than spawning a second file.

    This is the in-place counterpart of :func:`resolve.merge_entries` for the
    online enrichment path: it only touches list-shaped fields and never
    erases human-authored ``body`` text.
    """
    for a in (raw.get("aliases") or []):
        s = str(a).strip()
        if s and s not in entry.aliases:
            entry.aliases.append(s)
    for t in (raw.get("tags") or []):
        s = str(t).strip()
        if s and s not in entry.tags:
            entry.tags.append(s)
    body_fragment = str(raw.get("body", "")).strip()
    if body_fragment and body_fragment not in entry.body:
        suffix = f"\n\n🤖 第{chapter_number}章自动补充（原拟新建条目）：\n{body_fragment}"
        entry.body = entry.body.rstrip() + suffix + "\n"


def _valid_type(raw_type: Any) -> str:
    from ..codex.models import VALID_TYPES

    t = str(raw_type).strip().lower()
    if t in VALID_TYPES:
        return t
    return "character"


# Prefixes that the resolve module uses; mirrored here to avoid import cycle.
_TYPE_ID_PREFIX = {
    "character": "char_",
    "location": "loc_",
    "faction": "faction_",
    "item": "item_",
    "worldbuilding": "set_",
    "timeline": "evt_",
}


def _normalize_entity_id(raw_id: str, entity_type: str) -> str:
    """Ensure *raw_id* uses the standard prefix for its type.

    ``location_dome_city`` → ``loc_dome_city``
    ``faction_iron_bone_gang`` → ok as-is (matches type)
    """
    clean = slugify(raw_id)
    expected_prefix = _TYPE_ID_PREFIX.get(entity_type, "")
    if not expected_prefix:
        return clean
    # Strip any existing type prefix (char_, loc_, item_, faction_, set_, evt_),
    # then re-add the correct one for this entity type.
    all_prefixes = ("char_", "loc_", "item_", "faction_", "set_", "evt_")
    for pfx in all_prefixes:
        if clean.startswith(pfx):
            clean = clean[len(pfx):]
            break
    return expected_prefix + clean


def _format_existing_codex(
    entries: list[CodexEntry], entity_ids: list[str]
) -> str:
    """Format existing codex entries as context for the enrichment LLM call."""
    if not entries:
        missing = "\n".join(f"  - {eid}（档案未创建）" for eid in entity_ids)
        return f"以下实体目前尚无档案：\n{missing}" if missing else "（无已有档案）"

    lines: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            continue
        seen.add(entry.id)
        alias_str = f"（别名：{'、'.join(entry.aliases)}）" if entry.aliases else ""
        lines.append(f"### {entry.name}（id: {entry.id}，类型: {entry.type}）{alias_str}")
        body = entry.body.strip()
        if body:
            # Cap body length to avoid blowing the prompt.
            lines.append(body[:3000])
        else:
            lines.append("（档案为空）")
        lines.append("")
    return "\n".join(lines)


def _strip_new_prefix(eid: str) -> str:
    """Remove a lingering ``new:`` prefix from an entity id so it can safely
    be used as a filename (colon is illegal on Windows).

    The planner strips ``new:`` via :func:`resolve_entity_ids` when a codex is
    available, but outlines generated before the fix or from an edge-case code
    path may still carry it. This is the safety-net removal.
    """
    eid = (eid or "").strip()
    if eid.startswith("new:"):
        eid = slugify(eid[len("new:"):])
    return eid


def _format_planned_new(planned_ids: list[str]) -> str:
    """Format the 'this-chapter planned but not-yet-profiled' entity block.

    These are ids the chapter planner already assigned (they live in
    ``chXXX.md`` ``entities:``) but that don't yet have a codex entry. We
    surface them as a hard hint to the enricher: when the chapter prose
    mentions those same entities, the *only* id the enricher may use for the
    new ``new_entities`` entry is the planned one. Without this block the
    enricher freely renames the same concept (e.g. ``faction_iron_hand_gang``
    → ``faction_iron_fist_gang``) and produces the semantic fragmentation
    seen in the "测试" project after ch2.
    """
    if not planned_ids:
        return ""
    lines = ["--- 本章规划阶段已分配的实体 id（尚无档案；正文提及这些实体时必须复用此处的 id）---"]
    for eid in planned_ids:
        #Hint the codex type from the prefix so the LLM sees structure.
        prefix_id = eid.split("_", 1)[0] + "_"
        kind = {
            "char": "人物", "loc": "地点", "item": "物品",
            "faction": "势力", "set": "世界观", "evt": "时间线",
        }.get(prefix_id.rstrip("_"), "实体")
        lines.append(f"  - {eid}  [{kind}]")
    return "\n".join(lines) + "\n"
