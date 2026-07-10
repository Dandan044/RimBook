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
from ..codex.resolve import slugify
from ..config import GenerationConfig
from ..llm import LLMClient, Prompts
from ..memory.summarizer import Summarizer
from ..memory.entity_state import EntityStateStore
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
    ) -> None:
        self.llm = llm
        self.prompts = prompts
        self.codex = codex
        self.entity_state = entity_state
        self.summarizer = summarizer
        self.generation = generation

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
    ) -> EnrichResult:
        """Execute the full post-write pipeline for one chapter.

        Steps:
          1. Summarize (best-effort).
          2. Extract & apply entity state deltas (best-effort).
          3. LLM-driven codex enrichment (if *enrich* is True).
          4. Sync codex ``related`` fields.

        Returns an :class:`EnrichResult` even when individual steps fail, so
        the caller always gets a diagnostic report.
        """
        result = EnrichResult(chapter_number=number)

        # 1. Summarize.
        try:
            self.summarizer.summarize(number, draft_text)
        except Exception as exc:  # pragma: no cover
            logger.warning("Summarization failed for ch%d: %s", number, exc)

        # 2. Entity state deltas.
        entity_ids = chapter.all_entities()
        try:
            if entity_ids:
                deltas = self.summarizer.extract_entity_deltas(
                    number, draft_text, entity_ids
                )
                Summarizer.apply_deltas(deltas, self.entity_state, number)
        except Exception as exc:  # pragma: no cover
            logger.warning("State extraction failed for ch%d: %s", number, exc)

        # 3. LLM-driven codex enrichment.
        if enrich and entity_ids:
            try:
                enrich_result = self.enrich_codex(number, draft_text, entity_ids)
                result = self._apply_enrichment(enrich_result, number)
            except Exception as exc:  # pragma: no cover
                logger.warning("Enrichment failed for ch%d: %s", number, exc)

        # 4. Sync codex related fields (no placeholders — enrichment handles new entities).
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

        return result

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

        messages = self.llm.as_chat(
            system=self.prompts.codex_enrich_system,
            user=self.prompts.codex_enrich_user.format(
                chapter_number=chapter_number,
                chapter_text=chapter_text[:16384],  # safety cap
                existing_codex=existing_text,
            ),
        )
        gen = self.llm.generate_json(
            messages,
            model=self.llm.config.effective_check_model,
            temperature=0.2,
        )
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

            # Skip if already exists — the LLM may hallucinate an existing id.
            try:
                self.codex.read(eid)
                logger.info("Skipping new entity %s — already exists", eid)
                continue
            except Exception:
                pass

            entry = CodexEntry(
                id=eid,
                name=str(raw.get("name", eid)).strip() or eid,
                type=_valid_type(raw.get("type", "character")),
                aliases=[str(a).strip() for a in (raw.get("aliases") or []) if a],
                tags=[str(t).strip() for t in (raw.get("tags") or []) if t],
                related=[],
                body=str(raw.get("body", "")).strip(),
            )
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
            try:
                entry = self.codex.read(eid)
            except Exception:
                logger.warning("Enrich: update target %s not found, skipping", eid)
                continue

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
                        EnrichmentChange(entity_id=eid, action="updated", detail=f"追加发现：{entry.name}")
                    )
                if revs:
                    self.codex.write(entry)
                    logger.info("Enrich: added %d revelation(s) to %s", len(revs), eid)

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
                        EnrichmentChange(entity_id=eid, action="contradiction", detail=f"1 处矛盾：{desc[:40]}")
                    )
                if contras:
                    self.codex.write(entry)
                    logger.warning("Enrich: %d contradiction(s) flagged for %s", len(contras), eid)

        return result


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
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
