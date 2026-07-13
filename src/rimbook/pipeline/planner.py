"""The planner: synopsis -> volumes -> chapter beats.

Every planning call is a *checkpoint*: the LLM proposes a draft, we write it
to disk, and the user can review/edit before moving on. None of these calls
mutate state silently.

To prevent entity fragmentation (the LLM inventing a new id for an existing
character), the planner now receives the codex as a dependency and:

* injects the full list of existing entity ids (with names/aliases) into the
  chapter-planning prompt so the LLM can reuse them;
* resolves every id in the LLM's output through :mod:`rimbook.codex.resolve`
  so ``char_laozhao`` / ``lao_zhao`` style drift collapses to one canonical id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..codex import CodexStore, resolve_entity_ids
from ..llm import LLMClient, Prompts
from ..outline import ChapterOutline, OutlineStore, SceneBeat, VolumeOutline

__all__ = ["Planner", "ChapterPlanResult"]


@dataclass
class ChapterPlanResult:
    """Outcome of planning a chapter, including id-resolution diagnostics."""

    chapter: ChapterOutline
    resolved_ids: list[str] = field(default_factory=list)
    new_entity_ids: list[str] = field(default_factory=list)
    id_warnings: list[str] = field(default_factory=list)


class Planner:
    """Generate the layered outline of a novel."""

    def __init__(
        self,
        llm: LLMClient,
        prompts: Prompts,
        outline: OutlineStore,
        codex: CodexStore | None = None,
    ) -> None:
        self.llm = llm
        self.prompts = prompts
        self.outline = outline
        self.codex = codex

    # ------------------------------------------------------------------
    # Synopsis
    # ------------------------------------------------------------------
    def plan_synopsis(self, premise: str, *, persist: bool = True) -> str:
        """Generate the whole-novel synopsis from a short premise."""
        messages = self.llm.as_chat(
            system=self.prompts.synopsis_system,
            user=self.prompts.synopsis_user.format(premise=premise),
        )
        result = self.llm.generate(messages, temperature=0.8)
        text = result.content.strip()
        if persist:
            self.outline.write_synopsis(text)
        return text

    # ------------------------------------------------------------------
    # Volumes
    # ------------------------------------------------------------------
    def plan_volume(self, number: int, *, title: str = "", persist: bool = True) -> VolumeOutline:
        """Plan a single volume based on the synopsis + existing volumes."""
        synopsis = self.outline.read_synopsis().strip()
        existing = self.outline.list_volumes()
        existing_desc = _format_existing_volumes(existing)

        messages = self.llm.as_chat(
            system=self.prompts.volume_system,
            user=self.prompts.volume_user.format(
                synopsis=synopsis,
                existing_desc=existing_desc or "（无）",
                number=number,
                title_hint=(f"（标题：{title}）" if title else ""),
            ),
        )
        result = self.llm.generate(messages, temperature=0.8)
        arc = result.content.strip()

        vol = VolumeOutline(number=number, title=title, arc=arc)
        if persist:
            self.outline.write_volume(vol)
        return vol

    # ------------------------------------------------------------------
    # Chapter beats
    # ------------------------------------------------------------------
    def plan_chapter(
        self,
        number: int,
        *,
        volume: int | None = None,
        title: str = "",
        hint: str = "",
        persist: bool = True,
    ) -> ChapterOutline:
        """Plan a single chapter's beats (what should happen).

        .. deprecated:: caller
            Prefer :meth:`plan_chapter_detailed` which also returns id-resolution
            diagnostics. This method is kept for backward compatibility.
        """
        return self.plan_chapter_detailed(
            number, volume=volume, title=title, hint=hint, persist=persist
        ).chapter

    def plan_chapter_detailed(
        self,
        number: int,
        *,
        volume: int | None = None,
        title: str = "",
        hint: str = "",
        persist: bool = True,
    ) -> ChapterPlanResult:
        """Plan a chapter and return id-resolution diagnostics.

        Injects the existing codex entity list into the prompt, then resolves
        every entity id in the LLM's output against the codex so that
        fragmented ids collapse to their canonical form.
        """
        synopsis = self.outline.read_synopsis().strip()
        volume_arc = ""
        if volume is not None:
            vol = self.outline.read_volume(volume)
            if vol:
                volume_arc = vol.arc.strip()

        # Include chapters up to and including *number* so that regenerating
        # an already-written chapter's outline sees what already happened,
        # not just the chapters before it.
        prev = self.outline.list_chapters()
        prev_before = [c for c in prev if c.number < number]
        prev_desc = _format_prev_chapters(prev_before[-3:])

        # If this chapter already has an outline (e.g. regenerating),
        # include its existing summary so the LLM plans based on what
        # was already written, not as if the chapter is brand-new.
        current_chapter = next((c for c in prev if c.number == number), None)
        existing_summary_block = ""
        existing_beats_block = ""
        if current_chapter:
            if current_chapter.summary.strip():
                existing_summary_block = f"本章已有摘要（重新规划时请保持一致）：\n{current_chapter.summary.strip()}\n\n"
            if current_chapter.beats:
                beat_goals = "; ".join(b.goal for b in current_chapter.beats)
                existing_beats_block = f"本章已有 beat（参考已有内容重新规划）：\n{beat_goals}\n\n"

        entity_registry = self._format_entity_registry()

        messages = self.llm.as_chat(
            system=self.prompts.chapter_outline_system,
            user=self.prompts.chapter_outline_user.format(
                synopsis=synopsis,
                volume_arc_block=(f"本卷大纲：\n{volume_arc}\n\n" if volume_arc else ""),
                prev_desc_block=(f"近几章梗概：\n{prev_desc}\n\n" if prev_desc else ""),
                entity_registry_block=(
                    f"{entity_registry}\n\n" if entity_registry else ""
                ),
                hint_block=(f"作者提示：\n{hint}\n\n" if hint else ""),
                number=number,
                title_block=(f"标题：{title}" if title else ""),
            ),
        )
        # If regenerating an existing chapter, inject existing-context after
        # the standard prompt so the LLM is aware.
        if existing_summary_block or existing_beats_block:
            messages[-1]["content"] += "\n\n" + existing_summary_block + existing_beats_block + "请基于上述已有内容为第 {number} 章重新规划 beat。".replace("{number}", str(number))
        # Ask for JSON so we can parse beats + entities reliably.
        result = self.llm.generate_json(messages, temperature=0.7)
        chapter, warnings = _parse_chapter_json(
            number, result, volume=volume, title=title, codex=self.codex
        )

        # Preserve the existing summary so regeneration doesn't wipe it.
        if current_chapter and current_chapter.summary.strip():
            chapter.summary = current_chapter.summary

        # Collect diagnostics about new vs reused ids.
        resolved_ids: list[str] = []
        new_ids: list[str] = []
        if self.codex is not None:
            all_ids = chapter.all_entities()
            resolved_ids, log = resolve_entity_ids(all_ids, self.codex)
            for r in log:
                if r.is_new:
                    new_ids.append(r.canonical_id)

        if persist:
            self.outline.write_chapter(chapter)
        return ChapterPlanResult(
            chapter=chapter,
            resolved_ids=resolved_ids,
            new_entity_ids=new_ids,
            id_warnings=warnings,
        )

    def _format_entity_registry(self) -> str:
        """Build the 'existing entities' block for the chapter-planning prompt."""
        if self.codex is None:
            return ""
        entries = list(self.codex.iter_all())
        if not entries:
            return ""
        lines = ["已有实体清单（entities 字段必须复用这里的 id，新实体才用 new: 前缀）："]
        for e in entries:
            alias_str = f"（别名：{'、'.join(e.aliases)}）" if e.aliases else ""
            lines.append(f"  - {e.id}：{e.name}{alias_str}  [{e.type}]")
        return "\n".join(lines)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _format_existing_volumes(volumes: list[VolumeOutline]) -> str:
    if not volumes:
        return ""
    return "\n\n".join(
        f"第{v.number}卷《{v.title}》：{v.arc.strip()}" for v in volumes
    )


def _format_prev_chapters(chapters: list[ChapterOutline]) -> str:
    if not chapters:
        return ""
    parts = []
    for c in chapters:
        beat_goals = "; ".join(b.goal for b in c.beats) or "(无beat)"
        parts.append(
            f"第{c.number}章《{c.title}》计划：{beat_goals}"
            + (f"；摘要：{c.summary.strip()}" if c.summary.strip() else "")
        )
    return "\n".join(parts)


def _parse_chapter_json(
    number: int,
    data: dict,
    *,
    volume: int | None,
    title: str,
    codex: CodexStore | None = None,
) -> tuple[ChapterOutline, list[str]]:
    """Parse the LLM's chapter JSON, resolving entity ids against the codex.

    Returns ``(chapter, warnings)`` where *warnings* are human-readable notes
    about ids that were remapped (e.g. fuzzy matches).
    """
    import logging

    log = logging.getLogger(__name__)
    warnings: list[str] = []

    title = title or str(data.get("title", "") or "")
    tags = list(data.get("tags") or [])
    notes = str(data.get("notes", "") or "")
    beats_raw = data.get("beats") or []

    # Resolve ids: LLM may produce drift (char_laozhao vs lao_zhao). If a codex
    # store is available, normalize every id through resolve_entity_id.
    def _resolve_list(raw_ids: list[str]) -> list[str]:
        if codex is None:
            return [str(x) for x in raw_ids if str(x).strip()]
        from ..codex import resolve_entity_ids

        resolved, res_log = resolve_entity_ids([str(x) for x in raw_ids], codex)
        for r in res_log:
            if r.match_reason.startswith("fuzzy") or r.match_reason.startswith("guessed-name"):
                warnings.append(
                    f"实体 id 规范化：{r.raw_id or r.canonical_id} → {r.canonical_id}（{r.match_reason}）"
                )
        for r in res_log:
            if r.is_new:
                warnings.append(f"新实体：{r.canonical_id}（请稍后在 codex 中补充档案）")
        return resolved

    entities = _resolve_list(list(data.get("entities") or []))
    beats: list[SceneBeat] = []
    for b in beats_raw:
        if not isinstance(b, dict):
            continue
        beat_entities = _resolve_list(list(b.get("entities") or []))
        beats.append(
            SceneBeat(
                goal=str(b.get("goal", "")).strip(),
                conflict=str(b.get("conflict", "")).strip(),
                outcome=str(b.get("outcome", "")).strip(),
                entities=beat_entities,
            )
        )

    # Merge per-scene entity ids up to chapter level too (deduped, ordered).
    all_ents: list[str] = []
    seen: set[str] = set()
    for eid in [*entities, *(e for b in beats for e in b.entities)]:
        if eid and eid not in seen:
            seen.add(eid)
            all_ents.append(eid)

    chapter = ChapterOutline(
        number=number,
        title=title,
        volume=volume,
        beats=beats,
        entities=all_ents,
        tags=tags,
        notes=notes,
    )
    return chapter, warnings
