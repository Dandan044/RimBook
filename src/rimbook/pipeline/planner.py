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

import json
from collections.abc import Generator
from dataclasses import dataclass, field

from ..codex import CodexStore, resolve_entity_ids
from ..llm import LLMClient, Prompts
from ..llm.trace import NULL_TRACE, TraceStore
from ..memory.threads import ThreadStore
from ..outline import (
    ChapterOutline, OutlineStore, SceneBeat, VolumeOutline,
    RawBeat, RefinedBeat, ChapterAssignment, VolumeBeatData, MicroScene,
)

__all__ = ["Planner", "ChapterPlanResult", "VolumePlanResult"]


@dataclass
class ChapterPlanResult:
    """Outcome of planning a chapter, including id-resolution diagnostics."""

    chapter: ChapterOutline
    resolved_ids: list[str] = field(default_factory=list)
    new_entity_ids: list[str] = field(default_factory=list)
    id_warnings: list[str] = field(default_factory=list)


@dataclass
class VolumePlanResult:
    """Outcome of planning a volume together with its chapter beats."""

    volume: VolumeOutline
    chapters: list[ChapterOutline]
    warnings: list[str] = field(default_factory=list)


class Planner:
    """Generate the layered outline of a novel."""

    def __init__(
        self,
        llm: LLMClient,
        prompts: Prompts,
        outline: OutlineStore,
        codex: CodexStore | None = None,
        *,
        threads: ThreadStore | None = None,
        trace: TraceStore | None = None,
        project_name: str = "",
    ) -> None:
        self.llm = llm
        self.prompts = prompts
        self.outline = outline
        self.codex = codex
        self.threads = threads
        self.trace = trace if trace is not None else NULL_TRACE
        self.project_name = project_name

    # ------------------------------------------------------------------
    # Synopsis
    # ------------------------------------------------------------------
    def plan_synopsis(self, premise: str, *, persist: bool = True) -> str:
        """Generate the whole-novel synopsis from a short premise."""
        messages = self.llm.as_chat(
            system=self.prompts.synopsis_system,
            user=self.prompts.synopsis_user.format(premise=premise),
        )
        with self.trace.begin("synopsis", project=self.project_name) as t:
            result = self.llm.generate(messages, temperature=0.8)
            t.record(messages, result)
        text = result.content.strip()
        if persist:
            self.outline.write_synopsis(text)
        return text

    # ------------------------------------------------------------------
    # Volumes
    # ------------------------------------------------------------------
    def plan_volume(
        self, number: int, *, title: str = "", persist: bool = True
    ) -> VolumePlanResult:
        """Batch-plan a volume and all its chapter beats in one conversation.

        Turn 1 returns structured volume JSON (title/arc/ending/chapter_count);
        turn 2 continues the same chat history and returns all chapter beats.
        Nothing is written until both rounds parse successfully.
        """
        if self.outline.read_volume(number) is not None:
            raise FileExistsError(f"第 {number} 卷已存在，禁止重复规划")

        synopsis = self.outline.read_synopsis().strip()
        existing = self.outline.list_volumes()
        existing_desc = _format_existing_volumes(existing)

        # Prior-chapter recaps: build on what actually happened, not just on
        # prior volume arcs. Cap to the most recent 8 chapters to bound length.
        prev = self.outline.list_chapters()
        prev_recap = _format_prev_chapters(prev[-8:]) if prev else ""
        entity_registry = self._format_entity_registry()
        # Open threads up to the latest written chapter — the volume should
        # advance or resolve them rather than letting them dangle.
        max_chapter = max((c.number for c in prev), default=0)
        open_threads = self._format_open_threads(max_chapter + 1)

        entity_registry_block = f"{entity_registry}\n\n" if entity_registry else ""
        open_threads_block = (
            f"未回收的情节线索（本卷应推进或回收，不得遗忘）：\n{open_threads}\n\n"
            if open_threads
            else ""
        )

        turn1_user = self.prompts.volume_user.format(
            synopsis=synopsis,
            existing_desc=existing_desc or "（无）",
            prev_recap_block=(
                f"前卷已写章节回顾（请与本卷衔接，避免重复或断层）：\n{prev_recap}\n\n"
                if prev_recap
                else ""
            ),
            entity_registry_block=entity_registry_block,
            open_threads_block=open_threads_block,
            number=number,
            title_hint=(f"（标题：{title}）" if title else ""),
        )
        messages = self.llm.as_chat(
            system=self.prompts.volume_system,
            user=turn1_user,
        )
        with self.trace.begin("volume", project=self.project_name, volume=number) as t:
            vol_data = self.llm.generate_json(messages, temperature=0.7)
            t.record(messages, vol_data, model=self.llm.default_model)

        vol_title, arc, ending, chapter_count, warnings = _parse_volume_json(
            vol_data, number=number, title_hint=title
        )

        start_number = self.outline.last_chapter_number() + 1
        history = [
            {"role": "user", "content": turn1_user},
            {
                "role": "assistant",
                "content": json.dumps(dict(vol_data), ensure_ascii=False),
            },
        ]
        messages2 = self.llm.as_chat(
            system=self.prompts.volume_chapters_system,
            user=self.prompts.volume_chapters_user.format(
                chapter_count=chapter_count,
                volume_title=vol_title,
                volume_arc=arc,
                volume_ending=ending,
                start_chapter_number=start_number,
                entity_registry_block=entity_registry_block,
                open_threads_block=open_threads_block,
            ),
            history=history,
        )
        with self.trace.begin(
            "volume_chapters", project=self.project_name, volume=number
        ) as t:
            ch_data = self.llm.generate_json(messages2, temperature=0.7)
            t.record(messages2, ch_data, model=self.llm.default_model)

        chapters, w2 = _parse_volume_chapters_json(
            ch_data,
            volume=number,
            start_number=start_number,
            expected_count=chapter_count,
            codex=self.codex,
        )
        warnings.extend(w2)

        vol = VolumeOutline(
            number=number,
            title=vol_title,
            arc=arc,
            ending=ending,
            chapters=[c.number for c in chapters],
            recap="",
        )
        if persist:
            self.outline.write_volume(vol)
            for ch in chapters:
                self.outline.write_chapter(ch)
            self.outline.sync_volume_chapters(number)
        return VolumePlanResult(volume=vol, chapters=chapters, warnings=warnings)

    # ------------------------------------------------------------------
    # Volumes v2: beat chain → refine → assemble
    # ------------------------------------------------------------------
    def plan_volume_v2(
        self, number: int, *, title: str = ""
    ) -> Generator[dict, None, None]:
        """Three-step volume planning pipeline (yields SSE event dicts).

        Step 1: Volume structure (same as plan_volume Turn 1).
        Step 2: Generate a continuous beat chain (not grouped by chapter).
        Step 3: Refine beats + assemble into chapters.

        Yields dicts like {"event": "step", "data": {...}} for SSE streaming.
        """
        if self.outline.read_volume(number) is not None:
            raise FileExistsError(f"第 {number} 卷已存在，禁止重复规划")

        # === Step 1: Volume structure ===
        yield {"event": "step", "data": {"step": 1, "status": "running", "message": "正在生成卷大纲与结局…"}}

        synopsis = self.outline.read_synopsis().strip()
        existing = self.outline.list_volumes()
        existing_desc = _format_existing_volumes(existing)
        prev = self.outline.list_chapters()
        prev_recap = _format_prev_chapters(prev[-8:]) if prev else ""
        entity_registry = self._format_entity_registry()
        max_chapter = max((c.number for c in prev), default=0)
        open_threads = self._format_open_threads(max_chapter + 1)

        entity_registry_block = f"{entity_registry}\n\n" if entity_registry else ""
        open_threads_block = (
            f"未回收的情节线索（本卷应推进或回收，不得遗忘）：\n{open_threads}\n\n"
            if open_threads else ""
        )

        turn1_user = self.prompts.volume_user.format(
            synopsis=synopsis,
            existing_desc=existing_desc or "（无）",
            prev_recap_block=(
                f"前卷已写章节回顾（请与本卷衔接，避免重复或断层）：\n{prev_recap}\n\n"
                if prev_recap else ""
            ),
            entity_registry_block=entity_registry_block,
            open_threads_block=open_threads_block,
            number=number,
            title_hint=(f"（标题：{title}）" if title else ""),
        )
        messages = self.llm.as_chat(system=self.prompts.volume_system, user=turn1_user)
        with self.trace.begin("volume_v2", project=self.project_name, volume=number) as t:
            vol_data = self.llm.generate_json(messages, temperature=0.7)
            t.record(messages, vol_data, model=self.llm.default_model)

        vol_title, arc, ending, chapter_count, warnings = _parse_volume_json(
            vol_data, number=number, title_hint=title
        )

        vol = VolumeOutline(number=number, title=vol_title, arc=arc, ending=ending, chapters=[], recap="")
        self.outline.write_volume(vol)

        yield {"event": "step", "data": {
            "step": 1, "status": "done",
            "message": "卷大纲已生成",
            "volume": {"number": number, "title": vol_title, "arc": arc, "ending": ending, "chapter_count": chapter_count},
        }}

        # === Step 2: Continuous beat chain ===
        min_beats = max(chapter_count * 3, 12)
        max_beats = chapter_count * 6
        yield {"event": "step", "data": {"step": 2, "status": "running", "message": f"正在生成连续 beat 链（{min_beats}~{max_beats} 个）…"}}

        history = [
            {"role": "user", "content": turn1_user},
            {"role": "assistant", "content": json.dumps(dict(vol_data), ensure_ascii=False)},
        ]
        messages2 = self.llm.as_chat(
            system=self.prompts.volume_beats_system.format(min_beats=min_beats, max_beats=max_beats),
            user=self.prompts.volume_beats_user.format(
                volume_title=vol_title,
                volume_arc=arc,
                volume_ending=ending,
                entity_registry_block=entity_registry_block,
                open_threads_block=open_threads_block,
                min_beats=min_beats,
                max_beats=max_beats,
            ),
            history=history,
        )
        with self.trace.begin("volume_beats", project=self.project_name, volume=number) as t:
            beats_data = self.llm.generate_json(messages2, temperature=0.7)
            t.record(messages2, beats_data, model=self.llm.default_model)

        raw_beats = _parse_raw_beats(beats_data, codex=self.codex)
        if len(raw_beats) < min_beats:
            warnings.append(f"beat 数量 {len(raw_beats)} 低于建议下限 {min_beats}")

        # Persist beats (step=2)
        beat_data = VolumeBeatData(volume=number, step=2, raw_beats=raw_beats)
        self.outline.save_volume_beats(beat_data)

        yield {"event": "step", "data": {
            "step": 2, "status": "done",
            "message": f"已生成 {len(raw_beats)} 个 beat",
            "beats": [b.model_dump() for b in raw_beats],
        }}

        # === Step 3: Refine + Assemble ===
        yield from self._step3_refine_and_assemble(
            number=number,
            vol_title=vol_title,
            arc=arc,
            ending=ending,
            chapter_count=chapter_count,
            raw_beats=raw_beats,
            start_chapter_number=max_chapter + 1,
        )

    def assemble_from_beats(
        self, volume_number: int, beats: list[RawBeat] | None = None
    ) -> Generator[dict, None, None]:
        """Re-run Step 3 (refine + assemble) using current or provided beats.

        If *beats* is None, loads raw_beats from the persisted beats file.
        Yields SSE event dicts for Step 3 only.
        """
        vol = self.outline.read_volume(volume_number)
        if vol is None:
            raise FileNotFoundError(f"第 {volume_number} 卷不存在")

        beat_data = self.outline.load_volume_beats(volume_number)
        if beats is None:
            if beat_data is None or not beat_data.raw_beats:
                raise ValueError(f"第 {volume_number} 卷没有已生成的 beat 数据")
            beats = beat_data.raw_beats

        # Determine chapter_count from volume or infer
        chapter_count = len(vol.chapters) if vol.chapters else max(len(beats) // 4, 3)
        # If volume has no chapters yet, use a reasonable default
        if not vol.chapters:
            chapter_count = max(min(len(beats) // 4, 12), 3)

        start_number = self.outline.last_chapter_number() + 1
        # If re-assembling, chapters already exist for this volume
        existing_vol_chapters = [c for c in self.outline.list_chapters() if c.volume == volume_number]
        if existing_vol_chapters:
            start_number = min(c.number for c in existing_vol_chapters)
            chapter_count = len(existing_vol_chapters)

        yield from self._step3_refine_and_assemble(
            number=volume_number,
            vol_title=vol.title,
            arc=vol.arc,
            ending=vol.ending,
            chapter_count=chapter_count,
            raw_beats=beats,
            start_chapter_number=start_number,
        )

    def _step3_refine_and_assemble(
        self,
        *,
        number: int,
        vol_title: str,
        arc: str,
        ending: str,
        chapter_count: int,
        raw_beats: list[RawBeat],
        start_chapter_number: int,
    ) -> Generator[dict, None, None]:
        """Step 3a: group + keynote; Step 3b: per-chapter MicroScenes; persist."""
        # --- 3a: Assemble into chapters + keynote ---
        yield {"event": "step", "data": {
            "step": 3, "status": "running", "phase": "grouping",
            "message": f"正在将 {len(raw_beats)} 个 beat 分组为 {chapter_count} 章并写章基调…",
        }}

        beats_json = json.dumps(
            [b.model_dump() for b in raw_beats], ensure_ascii=False, indent=1,
        )
        messages_assemble = self.llm.as_chat(
            system=self.prompts.beat_assemble_system.format(chapter_count=chapter_count),
            user=self.prompts.beat_assemble_user.format(
                volume_title=vol_title,
                volume_arc=arc,
                volume_ending=ending,
                beat_count=len(raw_beats),
                chapter_count=chapter_count,
                beats_json=beats_json,
            ),
        )
        with self.trace.begin("beat_assemble", project=self.project_name, volume=number) as t:
            assemble_data = self.llm.generate_json(
                messages_assemble, temperature=0.5, max_tokens=16000,
            )
            t.record(messages_assemble, assemble_data, model=self.llm.default_model)

        chapter_map, beat_pool = _parse_assemble_from_raw(assemble_data, raw_beats)

        yield {"event": "step", "data": {
            "step": 3, "status": "running", "phase": "refining",
            "message": f"正在为 {len(chapter_map)} 章生成细场景…",
        }}

        # --- 3b: Per-chapter micro-scenes ---
        chapters: list[ChapterOutline] = []
        for i, ca in enumerate(chapter_map):
            ch_number = start_chapter_number + i
            ch_beats = [beat_pool[bid] for bid in ca.beat_ids if bid in beat_pool]
            yield {"event": "progress", "data": {
                "message": f"细化第 {ch_number} 章《{ca.title or '未命名'}》（{i + 1}/{len(chapter_map)}）…",
            }}
            scene_beats = self._microscene_chapter(
                number=number,
                vol_title=vol_title,
                ca=ca,
                chapter_beats=ch_beats,
            )
            entities: list[str] = []
            seen: set[str] = set()
            for sb in scene_beats:
                for eid in sb.entities:
                    if eid and eid not in seen:
                        seen.add(eid)
                        entities.append(eid)
            chapters.append(ChapterOutline(
                number=ch_number,
                title=ca.title,
                volume=number,
                beats=scene_beats,
                entities=entities,
                tags=[],
                notes="",
                keynote=list(ca.keynote),
                purpose=ca.purpose,
                value_shift=ca.value_shift,
                tension=ca.tension,
                hook=ca.hook,
                story_date=ca.story_date,
                elapsed=ca.elapsed,
            ))

        # Persist beats file (step=3) — chapter_map holds keynote; no dual MicroScene store
        beat_data = VolumeBeatData(
            volume=number, step=3,
            raw_beats=raw_beats,
            refined_beats=[],
            chapter_map=chapter_map,
        )
        self.outline.save_volume_beats(beat_data)

        for ch in chapters:
            self.outline.write_chapter(ch)
        self.outline.sync_volume_chapters(number)

        yield {"event": "step", "data": {
            "step": 3, "status": "done",
            "message": f"已组装 {len(chapters)} 章（含基调与细场景）",
            "chapters": [
                {
                    "number": c.number,
                    "title": c.title,
                    "beat_count": len(c.beats),
                    "keynote_count": len(c.keynote),
                    "scene_count": sum(len(b.scenes) for b in c.beats),
                }
                for c in chapters
            ],
        }}

    def _microscene_chapter(
        self,
        *,
        number: int,
        vol_title: str,
        ca: ChapterAssignment,
        chapter_beats: list[RawBeat],
    ) -> list[SceneBeat]:
        """Step 3b: expand one chapter's beats into MicroScenes under keynote."""
        if not chapter_beats:
            return []

        keynote_block = "\n".join(f"- {k}" for k in ca.keynote) if ca.keynote else "（无）"
        beats_json = json.dumps(
            [b.model_dump() for b in chapter_beats], ensure_ascii=False, indent=1,
        )
        messages = self.llm.as_chat(
            system=self.prompts.beat_refine_system,
            user=self.prompts.beat_refine_user.format(
                volume_title=vol_title,
                chapter_title=ca.title or "",
                chapter_purpose=ca.purpose or "",
                chapter_hook=ca.hook or "",
                keynote_block=keynote_block,
                beats_json=beats_json,
            ),
        )
        with self.trace.begin(
            "beat_microscene",
            project=self.project_name,
            volume=number,
            chapter_title=ca.title,
        ) as t:
            try:
                data = self.llm.generate_json(messages, temperature=0.5, max_tokens=8000)
                t.record(messages, data, model=self.llm.default_model)
            except ValueError as exc:
                t.record(messages, None, model=self.llm.default_model, warnings=[str(exc)])
                return [
                    SceneBeat(
                        goal=b.goal, conflict=b.conflict, outcome=b.outcome,
                        entities=list(b.entities), scenes=[],
                    )
                    for b in chapter_beats
                ]
        return _parse_microscene_beats(data, chapter_beats)

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

        A volume must be specified (or inferred from an existing chapter when
        regenerating). Planning chapters without a volume is forbidden.
        """
        # Include chapters up to and including *number* so that regenerating
        # an already-written chapter's outline sees what already happened,
        # not just the chapters before it.
        prev = self.outline.list_chapters()
        current_chapter = next((c for c in prev if c.number == number), None)

        # When regenerating, fall back to the chapter's existing volume.
        if volume is None and current_chapter is not None:
            volume = current_chapter.volume
        if volume is None:
            raise ValueError("必须指定所属卷：禁止在没有卷的情况下规划章节")
        vol = self.outline.read_volume(volume)
        if vol is None:
            raise FileNotFoundError(f"第 {volume} 卷不存在，请先规划卷")
        volume_arc = vol.arc.strip()

        prev_before = [c for c in prev if c.number < number]
        prev_desc = _format_prev_chapters(prev_before[-3:])

        # If this chapter already has an outline (e.g. regenerating),
        # include its existing summary so the LLM plans based on what
        # was already written, not as if the chapter is brand-new.
        existing_summary_block = ""
        existing_beats_block = ""
        if current_chapter:
            if current_chapter.summary.strip():
                existing_summary_block = f"本章已有摘要（重新规划时请保持一致）：\n{current_chapter.summary.strip()}\n\n"
            if current_chapter.beats:
                beat_goals = "; ".join(b.goal for b in current_chapter.beats)
                existing_beats_block = f"本章已有 beat（参考已有内容重新规划）：\n{beat_goals}\n\n"

        synopsis = self.outline.read_synopsis().strip()
        entity_registry = self._format_entity_registry()
        open_threads = self._format_open_threads(number)

        messages = self.llm.as_chat(
            system=self.prompts.chapter_outline_system,
            user=self.prompts.chapter_outline_user.format(
                synopsis=synopsis,
                volume_arc_block=(f"本卷大纲：\n{volume_arc}\n\n" if volume_arc else ""),
                prev_desc_block=(f"近几章梗概：\n{prev_desc}\n\n" if prev_desc else ""),
                open_threads_block=(
                    f"未回收的情节线索（本章可推进或回收，不得遗忘）：\n{open_threads}\n\n"
                    if open_threads else ""
                ),
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
        with self.trace.begin("planner", project=self.project_name, chapter=number) as t:
            result = self.llm.generate_json(messages, temperature=0.7)
            t.record(messages, result, model=self.llm.default_model)
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
            self.outline.sync_volume_chapters(volume)
        return ChapterPlanResult(
            chapter=chapter,
            resolved_ids=resolved_ids,
            new_entity_ids=new_ids,
            id_warnings=warnings,
        )

    def _format_open_threads(self, number: int) -> str:
        """Format the unresolved plot threads for the chapter-planning prompt."""
        if self.threads is None:
            return ""
        try:
            return self.threads.format_open_threads(upto_chapter=number)
        except Exception:
            return ""

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
        extras = []
        if c.tension:
            extras.append(f"张力{c.tension}/5")
        if c.story_date:
            extras.append(f"故事时间：{c.story_date}")
        extra_str = f"（{'，'.join(extras)}）" if extras else ""
        parts.append(
            f"第{c.number}章《{c.title}》{extra_str}计划：{beat_goals}"
            + (f"；摘要：{c.summary.strip()}" if c.summary.strip() else "")
        )
    return "\n".join(parts)


def _parse_volume_json(
    data: dict,
    *,
    number: int,
    title_hint: str = "",
) -> tuple[str, str, str, int, list[str]]:
    """Return ``(title, arc, ending, chapter_count, warnings)``.

    ``ending`` must be non-empty. ``chapter_count`` is clamped to ``[3, 20]``
    with a soft warning when the raw value is outside that range.
    """
    warnings: list[str] = []
    title = (title_hint or "").strip() or str(data.get("title", "") or "").strip()
    arc = str(data.get("arc", "") or "").strip()
    ending = str(data.get("ending", "") or "").strip()
    if not ending:
        raise ValueError(f"第 {number} 卷规划缺少 ending")

    raw_count = data.get("chapter_count", 6)
    try:
        chapter_count = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"第 {number} 卷无效的 chapter_count: {raw_count!r}") from exc

    if chapter_count < 3 or chapter_count > 20:
        clamped = min(max(chapter_count, 3), 20)
        warnings.append(
            f"chapter_count={chapter_count} 超出建议范围 [3, 20]，已钳制为 {clamped}"
        )
        chapter_count = clamped

    return title, arc, ending, chapter_count, warnings


def _parse_volume_chapters_json(
    data: dict,
    *,
    volume: int,
    start_number: int,
    expected_count: int,
    codex: CodexStore | None,
) -> tuple[list[ChapterOutline], list[str]]:
    """Parse a ``chapters`` array; assign numbers ``start_number``.. sequentially.

    Reuses :func:`_parse_chapter_json` per item. Raises ``ValueError`` when the
    array length does not match ``expected_count``.
    """
    raw = data.get("chapters")
    if not isinstance(raw, list):
        raise ValueError("卷章节规划缺少 chapters 数组")
    if len(raw) != expected_count:
        raise ValueError(
            f"卷章节数量不符：期望 {expected_count}，实际 {len(raw)}"
        )

    chapters: list[ChapterOutline] = []
    warnings: list[str] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"第 {i + 1} 个章节项不是对象")
        chapter, w = _parse_chapter_json(
            start_number + i,
            item,
            volume=volume,
            title="",
            codex=codex,
        )
        chapters.append(chapter)
        warnings.extend(w)
    return chapters, warnings


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

    tension_raw = data.get("tension")
    try:
        tension = min(max(int(tension_raw), 0), 5) if tension_raw is not None else 0
    except (TypeError, ValueError):
        tension = 0

    chapter = ChapterOutline(
        number=number,
        title=title,
        volume=volume,
        beats=beats,
        entities=all_ents,
        tags=tags,
        notes=notes,
        purpose=str(data.get("purpose", "") or ""),
        value_shift=str(data.get("value_shift", "") or ""),
        tension=tension,
        hook=str(data.get("hook", "") or ""),
        story_date=str(data.get("story_date", "") or ""),
        elapsed=str(data.get("elapsed", "") or ""),
    )
    return chapter, warnings


# ----------------------------------------------------------------------
# v2 pipeline helpers
# ----------------------------------------------------------------------
def _parse_raw_beats(data: dict, *, codex: CodexStore | None = None) -> list[RawBeat]:
    """Parse the LLM's beat chain JSON into RawBeat objects."""
    raw = data.get("beats")
    if not isinstance(raw, list):
        raise ValueError("beat 链规划缺少 beats 数组")

    beats: list[RawBeat] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        beat_id = str(item.get("id", f"b{i + 1:02d}"))
        entities = [str(x) for x in (item.get("entities") or []) if str(x).strip()]
        # Resolve entity ids against codex if available
        if codex is not None and entities:
            entities, _ = resolve_entity_ids(entities, codex)
        beats.append(RawBeat(
            id=beat_id,
            goal=str(item.get("goal", "")).strip(),
            conflict=str(item.get("conflict", "")).strip(),
            outcome=str(item.get("outcome", "")).strip(),
            entities=entities,
            momentum=str(item.get("momentum", "")).strip(),
        ))
    if not beats:
        raise ValueError("beat 链为空")
    return beats


def _parse_assemble_from_raw(
    data: dict, raw_beats: list[RawBeat]
) -> tuple[list[ChapterAssignment], dict[str, RawBeat]]:
    """Parse Step 3a assemble JSON → chapter_map + beat id pool (incl. bridges)."""
    raw = data.get("chapters")
    if not isinstance(raw, list):
        raise ValueError("分组结果缺少 chapters 数组")

    beat_pool: dict[str, RawBeat] = {b.id: b for b in raw_beats}
    chapter_map: list[ChapterAssignment] = []

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        beat_ids = [str(x) for x in (item.get("beat_ids") or [])]
        for bb in item.get("bridge_beats") or []:
            if not isinstance(bb, dict):
                continue
            bridge = RawBeat(
                id=str(bb.get("id", f"b_bridge_{i}")),
                goal=str(bb.get("goal", "")).strip(),
                conflict=str(bb.get("conflict", "")).strip(),
                outcome=str(bb.get("outcome", "")).strip(),
                entities=[str(x) for x in (bb.get("entities") or []) if str(x).strip()],
                momentum=str(bb.get("momentum", "")).strip(),
            )
            beat_pool[bridge.id] = bridge
            # Insert bridge into beat_ids if missing (after referenced predecessor when possible)
            if bridge.id not in beat_ids:
                beat_ids.append(bridge.id)

        tension_raw = item.get("tension")
        try:
            tension = min(max(int(tension_raw), 0), 5) if tension_raw is not None else 0
        except (TypeError, ValueError):
            tension = 0

        keynote_raw = item.get("keynote") or []
        if isinstance(keynote_raw, str):
            keynote = [ln.strip().lstrip("-• ").strip() for ln in keynote_raw.splitlines() if ln.strip()]
        elif isinstance(keynote_raw, list):
            keynote = [str(x).strip() for x in keynote_raw if str(x).strip()]
        else:
            keynote = []

        chapter_map.append(ChapterAssignment(
            chapter=i + 1,
            title=str(item.get("title", "")).strip(),
            beat_ids=beat_ids,
            purpose=str(item.get("purpose", "")).strip(),
            value_shift=str(item.get("value_shift", "")).strip(),
            tension=tension,
            hook=str(item.get("hook", "")).strip(),
            story_date=str(item.get("story_date", "")).strip(),
            elapsed=str(item.get("elapsed", "")).strip(),
            keynote=keynote,
        ))

    if not chapter_map:
        raise ValueError("分组结果为空")
    return chapter_map, beat_pool


def _parse_microscene_beats(data: dict, fallback: list[RawBeat]) -> list[SceneBeat]:
    """Parse Step 3b micro-scene JSON into SceneBeat list."""
    raw = data.get("beats")
    by_id = {b.id: b for b in fallback}

    if not isinstance(raw, list):
        return [
            SceneBeat(goal=b.goal, conflict=b.conflict, outcome=b.outcome,
                      entities=list(b.entities), scenes=[])
            for b in fallback
        ]

    result: list[SceneBeat] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        beat_id = str(item.get("id", ""))
        fb = by_id.get(beat_id) or (fallback[i] if i < len(fallback) else None)
        scenes = _parse_microscenes(item.get("scenes") or [])
        result.append(SceneBeat(
            goal=str(item.get("goal", fb.goal if fb else "")).strip(),
            conflict=str(item.get("conflict", fb.conflict if fb else "")).strip(),
            outcome=str(item.get("outcome", fb.outcome if fb else "")).strip(),
            entities=list(item.get("entities", fb.entities if fb else [])),
            scenes=scenes,
        ))
        if beat_id:
            seen_ids.add(beat_id)

    for fb in fallback:
        if fb.id not in seen_ids and not any(
            r.goal == fb.goal and r.outcome == fb.outcome for r in result
        ):
            # Append missing beats with empty scenes
            if len(result) < len(fallback):
                result.append(SceneBeat(
                    goal=fb.goal, conflict=fb.conflict, outcome=fb.outcome,
                    entities=list(fb.entities), scenes=[],
                ))
    # If LLM returned fewer, pad from fallback preserving order
    if len(result) < len(fallback):
        for fb in fallback[len(result):]:
            result.append(SceneBeat(
                goal=fb.goal, conflict=fb.conflict, outcome=fb.outcome,
                entities=list(fb.entities), scenes=[],
            ))
    return result


def _parse_microscenes(raw: list) -> list[MicroScene]:
    scenes: list[MicroScene] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        try:
            words = max(int(s.get("words") or 0), 0)
        except (TypeError, ValueError):
            words = 0
        scenes.append(MicroScene(
            action=str(s.get("action", "")).strip(),
            dialogue=str(s.get("dialogue", "")).strip(),
            event=str(s.get("event", "")).strip(),
            technique=str(s.get("technique", "")).strip(),
            pacing=str(s.get("pacing", "")).strip(),
            words=words,
        ))
    return scenes


# ----------------------------------------------------------------------
# Legacy helpers (kept for older tests / callers)
# ----------------------------------------------------------------------
def _parse_refined_beats(data: dict, fallback: list[RawBeat]) -> list[RefinedBeat]:
    """Parse refined beats from LLM output, falling back to raw beats on mismatch."""
    raw = data.get("beats")
    if not isinstance(raw, list):
        return [RefinedBeat(**b.model_dump()) for b in fallback]

    refined: list[RefinedBeat] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        fb = fallback[i] if i < len(fallback) else None
        beat_id = str(item.get("id", fb.id if fb else f"b{i + 1:02d}"))
        refined.append(RefinedBeat(
            id=beat_id,
            goal=str(item.get("goal", fb.goal if fb else "")).strip(),
            conflict=str(item.get("conflict", fb.conflict if fb else "")).strip(),
            outcome=str(item.get("outcome", fb.outcome if fb else "")).strip(),
            entities=list(item.get("entities", fb.entities if fb else [])),
            momentum=str(item.get("momentum", fb.momentum if fb else "")).strip(),
            technique=str(item.get("technique", "")).strip(),
            plot_detail=str(item.get("plot_detail", "")).strip(),
            thematic_expr=str(item.get("thematic_expr", "")).strip(),
            pacing_note=str(item.get("pacing_note", "")).strip(),
            is_bridge=False,
        ))
    if len(refined) < len(fallback):
        for fb in fallback[len(refined):]:
            refined.append(RefinedBeat(**fb.model_dump()))
    return refined


def _parse_assemble_result(
    data: dict, refined_beats: list[RefinedBeat]
) -> tuple[list[ChapterAssignment], list[RefinedBeat]]:
    """Legacy assemble parser — prefer :func:`_parse_assemble_from_raw`."""
    raw_as = [RawBeat(**{k: getattr(b, k) for k in ("id", "goal", "conflict", "outcome", "entities", "momentum")})
              for b in refined_beats]
    chapter_map, pool = _parse_assemble_from_raw(data, raw_as)
    # Rebuild refined list from pool (bridges included)
    all_refined = [
        next((r for r in refined_beats if r.id == bid), RefinedBeat(**pool[bid].model_dump()))
        for bid in {b for ca in chapter_map for b in ca.beat_ids}
        if bid in pool
    ]
    # Preserve original order of refined + append new bridges
    by_id = {b.id: b for b in refined_beats}
    out: list[RefinedBeat] = list(refined_beats)
    for bid, rb in pool.items():
        if bid not in by_id:
            out.append(RefinedBeat(**rb.model_dump(), is_bridge=True))
    return chapter_map, out


def _beats_to_chapters(
    chapter_map: list[ChapterAssignment],
    all_refined: list[RefinedBeat],
    *,
    volume: int,
    start_number: int,
) -> list[ChapterOutline]:
    """Legacy converter — maps RefinedBeat → SceneBeat without MicroScenes."""
    beat_index: dict[str, RefinedBeat] = {b.id: b for b in all_refined}
    chapters: list[ChapterOutline] = []

    for i, ca in enumerate(chapter_map):
        ch_number = start_number + i
        scene_beats: list[SceneBeat] = []
        entities: list[str] = []
        seen_ents: set[str] = set()

        for bid in ca.beat_ids:
            rb = beat_index.get(bid)
            if rb is None:
                continue
            scene_beats.append(SceneBeat(
                goal=rb.goal,
                conflict=rb.conflict,
                outcome=rb.outcome,
                entities=rb.entities,
            ))
            for eid in rb.entities:
                if eid and eid not in seen_ents:
                    seen_ents.add(eid)
                    entities.append(eid)

        chapters.append(ChapterOutline(
            number=ch_number,
            title=ca.title,
            volume=volume,
            beats=scene_beats,
            entities=entities,
            tags=[],
            notes="",
            keynote=list(ca.keynote),
            purpose=ca.purpose,
            value_shift=ca.value_shift,
            tension=ca.tension,
            hook=ca.hook,
            story_date=ca.story_date,
            elapsed=ca.elapsed,
        ))
    return chapters
