"""Chapter summarization.

After a chapter is written, we distill it into a compact summary that lives
in the chapter outline file. This summary replaces the full prose in all
*future* context windows, which is what lets a novel scale past the model's
context limit without the LLM "forgetting" what happened.

This module also extracts per-entity state deltas from a chapter, so that
character location/knowledge/possessions stay current (see
:mod:`entity_state`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import yaml

from ..llm import LLMClient, Prompts
from ..llm.trace import NULL_TRACE, TraceStore
from ..outline.store import OutlineStore
from .entity_state import EntityState, EntityStateStore, KnowledgeItem, PossessionItem

__all__ = ["Summarizer", "EntityDelta"]


@dataclass
class EntityDelta:
    """A parsed state update for one entity, extracted from a chapter.

    Each field is optional: present means "changed this chapter". Lists come
    in ``add``/``remove`` pairs so the model can express both acquiring and
    losing items/knowledge; relationships map target id → current standing,
    with a value of ``null``/empty meaning the relationship ended.
    """

    entity_id: str
    location: str | None = None
    status: str | None = None
    knowledge: list[str] | None = None
    possessions: list[str] | None = None
    relationships: dict[str, str | None] | None = None
    # Removals (lifecycle support — fixes the "only ever grows" problem).
    knowledge_remove: list[str] | None = None
    possessions_remove: list[str] | None = None


class Summarizer:
    """Generate chapter summaries and entity-state deltas."""

    def __init__(
        self,
        llm: LLMClient,
        prompts: Prompts,
        outline: OutlineStore,
        *,
        trace: TraceStore | None = None,
        project_name: str = "",
    ) -> None:
        self.llm = llm
        self.prompts = prompts
        self.outline = outline
        self.trace = trace if trace is not None else NULL_TRACE
        self.project_name = project_name

    def summarize(self, chapter_number: int, chapter_text: str) -> str:
        """Generate and persist a summary for a written chapter."""
        beat_block = ""
        try:
            ch = self.outline.read_chapter(chapter_number)
            if ch and ch.beats:
                goals = "; ".join(b.goal for b in ch.beats)
                beat_block = (
                    f"本章计划 beat（摘要应对照计划与实际，"
                    f"若正文偏离计划请在摘要中注明）：{goals}\n\n"
                )
        except Exception:
            beat_block = ""
        messages = self.llm.as_chat(
            system=self.prompts.summarize_system,
            user=self.prompts.summarize_user.format(
                chapter_number=chapter_number,
                chapter_text=chapter_text,
                beat_block=beat_block,
            ),
        )
        with self.trace.begin(
            "summarizer", project=self.project_name, chapter=chapter_number
        ) as t:
            result = self.llm.generate(
                messages,
                temperature=0.3,
                model=self.llm.config.effective_check_model,
            )
            t.record(messages, result)
        summary = result.content.strip()
        # Persist back into the chapter outline file.
        self.outline.update_chapter_summary(chapter_number, summary)
        return summary

    # ------------------------------------------------------------------
    # Hierarchical memory: volume recap + story-so-far
    # ------------------------------------------------------------------
    def summarize_volume(self, volume_number: int, *, persist: bool = True) -> str:
        """Compress a volume's chapter summaries into a realized recap.

        Unlike the planning-time ``arc``, the recap reflects what *actually*
        happened. It is injected into future chapters' context in place of
        the individual chapter summaries once they scroll out of the window.
        """
        vol = self.outline.read_volume(volume_number)
        if vol is None:
            raise FileNotFoundError(f"Volume {volume_number} has no outline")
        chapters = [
            c for c in self.outline.list_chapters()
            if c.volume == volume_number and c.summary.strip()
        ]
        if not chapters:
            return ""
        blob = "\n".join(
            f"第 {c.number} 章《{c.title}》：{c.summary.strip()}" for c in chapters
        )
        messages = self.llm.as_chat(
            system=self.prompts.volume_recap_system,
            user=self.prompts.volume_recap_user.format(
                volume_number=volume_number,
                volume_title=vol.title or "",
                chapter_summaries=blob,
            ),
        )
        with self.trace.begin(
            "volume_recap", project=self.project_name, volume=volume_number
        ) as t:
            result = self.llm.generate(
                messages,
                temperature=0.3,
                model=self.llm.config.effective_check_model,
            )
            t.record(messages, result)
        recap = result.content.strip()
        if persist and recap:
            vol.recap = recap
            self.outline.write_volume(vol)
        return recap

    def update_story_so_far(self, upto_chapter: int, *, persist: bool = True) -> str:
        """Refresh the rolling whole-book recap up to *upto_chapter*.

        Incremental: takes the previous story-so-far text plus the summaries
        of chapters written since, and asks the LLM to fold them together.
        """
        previous, prev_upto = self.outline.read_story_so_far()
        new_chapters = [
            c for c in self.outline.list_chapters()
            if prev_upto < c.number <= upto_chapter and c.summary.strip()
        ]
        if not new_chapters:
            return previous
        new_blob = "\n".join(
            f"第 {c.number} 章《{c.title}》：{c.summary.strip()}" for c in new_chapters
        )
        messages = self.llm.as_chat(
            system=self.prompts.story_so_far_system,
            user=self.prompts.story_so_far_user.format(
                prev_upto=prev_upto or 0,
                previous=previous or "（尚无，故事刚开始）",
                new_summaries=new_blob,
                upto=upto_chapter,
            ),
        )
        with self.trace.begin(
            "story_so_far", project=self.project_name, chapter=upto_chapter
        ) as t:
            result = self.llm.generate(
                messages,
                temperature=0.3,
                model=self.llm.config.effective_check_model,
            )
            t.record(messages, result)
        text = result.content.strip()
        if persist and text:
            self.outline.write_story_so_far(text, upto_chapter)
        return text

    def extract_entity_deltas(
        self,
        chapter_number: int,
        chapter_text: str,
        entity_ids: list[str],
        *,
        codex=None,
        entity_states_text: str = "",
    ) -> list[EntityDelta]:
        """Ask the model how each entity's state changed during the chapter.

        *codex* (optional) lets the parser normalize drifted entity ids back
        to their canonical form so deltas are recorded against the right
        entity's state file — without it, a drifted id is silently dropped.
        """
        if not entity_ids:
            return []
        messages = self.llm.as_chat(
            system=self.prompts.entity_delta_system,
            user=self.prompts.entity_delta_user.format(
                chapter_number=chapter_number,
                chapter_text=chapter_text,
                entity_ids=entity_ids,
                entity_states_block=entity_states_text,
            ),
        )
        with self.trace.begin(
            "entity_delta", project=self.project_name, chapter=chapter_number
        ) as t:
            data = self.llm.generate_json(
                messages,
                model=self.llm.config.effective_check_model,
                temperature=0.0,
            )
            t.record(messages, data, model=self.llm.config.effective_check_model)
        return _parse_deltas(data, entity_ids, codex=codex)

    @staticmethod
    def apply_deltas(
        deltas: list[EntityDelta],
        store: EntityStateStore,
        chapter_number: int,
    ) -> list[EntityState]:
        """Merge deltas into existing entity state files.

        Supports the full state lifecycle:
        * ``location``/``status`` overwrite (latest wins);
        * ``knowledge``/``possessions`` extend (new items added);
        * ``knowledge_remove``/``possessions_remove`` remove items;
        * ``relationships`` with a real value update the relationship; a value
          of ``None`` *removes* the relationship (it ended this chapter).
        """
        updated: list[EntityState] = []
        for d in deltas:
            current = store.get(d.entity_id)
            if d.location:
                current.location = d.location
            if d.status:
                current.status = d.status
            if d.knowledge:
                current.knowledge = _extend_knowledge(current.knowledge, d.knowledge, chapter_number)
            if d.possessions:
                current.possessions = _extend_possessions(current.possessions, d.possessions, chapter_number)
            if d.knowledge_remove:
                current.knowledge = _subtract_knowledge(current.knowledge, d.knowledge_remove)
            if d.possessions_remove:
                current.possessions = _subtract_possessions(current.possessions, d.possessions_remove)
            if d.relationships:
                for target_id, standing in d.relationships.items():
                    if standing is None or standing == "":
                        # Relationship ended — remove it.
                        current.relationships.pop(target_id, None)
                    else:
                        current.relationships[target_id] = standing
            current.last_seen_chapter = max(current.last_seen_chapter, chapter_number)
            store.save(current)
            updated.append(current)
        return updated


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _parse_deltas(
    data: dict[str, Any],
    entity_ids: list[str],
    *,
    codex=None,
) -> list[EntityDelta]:
    raw = data.get("entities") or []
    out: list[EntityDelta] = []
    known = set(entity_ids)
    # Lazily import resolve to avoid a heavy import in callers that never
    # pass a codex (e.g. plain summarization with no state extraction).
    resolve_entity_id = None
    if codex is not None:
        from ..codex.resolve import resolve_entity_id

    for item in raw:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("entity_id") or "").strip()
        if not eid:
            continue

        # Defensive: if a ``new:`` prefix survived into the entity id (e.g.
        # because the planner was called without a codex before the June 2024
        # fix), silently strip it.  The colon is illegal in a Windows
        # filename, and ``new:`` serves no purpose after entity creation.
        if eid.startswith("new:"):
            from ..codex.resolve import slugify

            eid = slugify(eid[len("new:"):])

        # Only accept ids we asked about, to avoid hallucinated entities.
        # If the LLM returned a drifted id (e.g. ``char_linyuan`` instead of
        # the canonical ``char_lin_yuan``), try resolving it through the
        # codex first so the delta lands on the right entity's state file
        # instead of being silently dropped.
        if known and eid not in known and resolve_entity_id is not None:
            resolved = resolve_entity_id(eid, codex)
            if resolved.is_existing and resolved.canonical_id in known:
                eid = resolved.canonical_id
        if known and eid not in known:
            continue
        out.append(
            EntityDelta(
                entity_id=eid,
                location=_opt_str(item.get("location")),
                status=_opt_str(item.get("status")),
                knowledge=_opt_list(item.get("knowledge")),
                possessions=_opt_list(item.get("possessions")),
                knowledge_remove=_opt_list(item.get("knowledge_remove")),
                possessions_remove=_opt_list(item.get("possessions_remove")),
                relationships=_opt_nullable_dict(item.get("relationships")),
            )
        )
    return out


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _opt_list(v: Any) -> list[str] | None:
    if v is None:
        return None
    if isinstance(v, str):
        return [v] if v else None
    if isinstance(v, list):
        out = [str(x).strip() for x in v if str(x).strip()]
        return out or None
    return None


def _opt_nullable_dict(v: Any) -> dict[str, str | None] | None:
    """Like _opt_dict but preserves explicit ``null`` values.

    A null value signals "this relationship ended", which :meth:`apply_deltas`
    interprets as a removal. So we must not coerce null → "None" string.
    """
    if not isinstance(v, dict):
        return None
    out: dict[str, str | None] = {}
    for k, val in v.items():
        if not k:
            continue
        if val is None:
            out[str(k)] = None
        else:
            out[str(k)] = str(val)
    return out or None


def _subtract(base: list[str], to_remove: list[str]) -> list[str]:
    """Remove items from *base*, matching case-insensitively. Preserves order."""
    remove_set = {x.lower() for x in to_remove}
    return [x for x in base if x.lower() not in remove_set]


def _extend_knowledge(
    base: list[KnowledgeItem], extra: list[str], chapter: int
) -> list[KnowledgeItem]:
    seen = {k.fact for k in base}
    for fact in extra:
        if fact and fact not in seen:
            base.append(KnowledgeItem(fact=fact, source_chapter=chapter))
            seen.add(fact)
    return base


def _extend_possessions(
    base: list[PossessionItem], extra: list[str], chapter: int
) -> list[PossessionItem]:
    seen = {p.item for p in base}
    for item in extra:
        if item and item not in seen:
            base.append(PossessionItem(item=item, acquired_chapter=chapter))
            seen.add(item)
    return base


def _subtract_knowledge(base: list[KnowledgeItem], to_remove: list[str]) -> list[KnowledgeItem]:
    remove_set = {x.lower() for x in to_remove}
    return [k for k in base if k.fact.lower() not in remove_set]


def _subtract_possessions(base: list[PossessionItem], to_remove: list[str]) -> list[PossessionItem]:
    remove_set = {x.lower() for x in to_remove}
    return [p for p in base if p.item.lower() not in remove_set]


def _extend_unique(base: list[str], extra: list[str]) -> list[str]:
    out = list(base)
    seen = set(base)
    for x in extra:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out
