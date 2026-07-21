"""Context assembly — the single most important component in RimBook.

On every generation, instead of dumping an entire novel into the prompt, we
assemble a small, carefully layered context that contains *exactly* what the
model needs to write the current chapter consistently:

0. The project style bible (narrative voice/POV/tone rules),
1. Relevant codex entries (explicit via the chapter's entity ids/tags,
   supplemented by optional vector retrieval),
2. The synopsis (original plan) + hierarchical memory: the rolling
   story-so-far recap, completed-volume recaps, and the current volume arc,
3. Recent chapter *summaries* (what happened before),
4. A sliding window of recent *full prose* (voice/tense continuity),
5. The *current* state of every entity involved (anti-OOC),
6. Open plot threads (foreshadowing / suspense that must not be forgotten),
7. The chapter beat itself (what must happen now).

The result is a single :class:`AssembledContext` string + token estimate,
ready to feed to the writer.

``assemble_for_chapter(..., mode="check")`` produces a leaner variant for the
consistency checker: it drops the style bible and the full recent prose
(the checker receives the chapter text separately), keeping only the
reference material needed to audit consistency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..codex import CodexEntry, CodexStore
from ..config import GenerationConfig
from ..outline import ChapterOutline, OutlineStore
from ..project import ProjectPaths
from .entity_state import EntityState, EntityStateStore
from .threads import ThreadStore
from .window import SlidingWindow

__all__ = ["ContextAssembler", "AssembledContext", "SectionInfo"]


@dataclass
class SectionInfo:
    """One section of the assembled context, with metadata for structured display."""

    key: str          # machine-readable key, e.g. "codex", "synopsis", "state"
    label: str        # display label, e.g. "设定档案（必须严格遵守）"
    text: str         # full text content of this section
    tokens: int = 0   # estimated token count
    # For codex section: per-entity sub-items
    entities: list[dict] = field(default_factory=list)
    # Generic sub-sections (for state, summaries, etc.)
    sub_items: list[dict] = field(default_factory=list)


@dataclass
class AssembledContext:
    """The fully assembled prompt context for one generation."""

    text: str
    sections: dict[str, str] = field(default_factory=dict)
    section_list: list[SectionInfo] = field(default_factory=list)
    codex_used: list[CodexEntry] = field(default_factory=list)
    entity_states_used: list[EntityState] = field(default_factory=list)
    recent_chapters: list[int] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - thin convenience
        return self.text


class ContextAssembler:
    """Build the layered context for a chapter generation."""

    def __init__(
        self,
        paths: ProjectPaths,
        *,
        codex: CodexStore,
        outline: OutlineStore,
        entity_state: EntityStateStore,
        window: SlidingWindow,
        generation: GenerationConfig,
        retriever=None,  # optional VectorRetriever (Phase 2); avoids hard dep
        threads: ThreadStore | None = None,
    ) -> None:
        self.paths = paths
        self.codex = codex
        self.outline = outline
        self.entity_state = entity_state
        self.window = window
        self.generation = generation
        self.retriever = retriever
        self.threads = threads if threads is not None else ThreadStore(paths)

    def assemble_for_chapter(
        self, chapter: ChapterOutline, *, mode: str = "write"
    ) -> AssembledContext:
        """Assemble context for the given chapter outline.

        *mode* is ``"write"`` (full context for prose generation) or
        ``"check"`` (leaner reference material for the consistency checker:
        no style bible, no recent full prose).
        """
        sections: list[str] = []
        emit = sections.append  # local alias
        section_list: list[SectionInfo] = []
        for_writing = mode != "check"

        # --- 0. Style bible (voice card) --------------------------------
        if for_writing:
            style = self.outline.read_style().strip()
            if style:
                style_text = (
                    "## 写作风格指南（人称/视角/语言基调，必须严格遵守）\n"
                    f"{style}\n\n"
                )
                emit(style_text)
                section_list.append(SectionInfo(
                    key="style",
                    label="写作风格指南（必须严格遵守）",
                    text=style,
                    tokens=_estimate_tokens(style),
                ))

        # --- 1. Relevant codex entries ---------------------------------
        entity_ids = chapter.all_entities()
        codex_entries, codex_truncated = self._gather_codex(entity_ids, chapter)
        if codex_entries:
            codex_text_parts: list[str] = ["## 设定档案（必须严格遵守）\n"]
            entity_infos: list[dict] = []
            for entry in codex_entries:
                type_label = _type_label(entry.type)
                header = f"### [{type_label}] {entry.name}（id: {entry.id}）\n"
                codex_text_parts.append(header)
                if entry.aliases:
                    codex_text_parts.append(
                        f"别名：{'、'.join(entry.aliases)}\n"
                    )
                body_text = _demote_headings(entry.body.strip())
                codex_text_parts.append(body_text + "\n")
                # Include revelations from structured data
                if entry.revelations:
                    codex_text_parts.append("#### 章节发现\n")
                    for rev in entry.revelations:
                        codex_text_parts.append(
                            f"- 第{rev.chapter}章：{rev.content}\n"
                        )
                # Include contradictions
                if entry.contradictions:
                    codex_text_parts.append("#### 待审核矛盾\n")
                    for con in entry.contradictions:
                        status = "已解决" if con.resolved else "未解决"
                        codex_text_parts.append(
                            f"- 第{con.chapter}章 [{status}]：{con.description}\n"
                        )
                        if con.evidence:
                            codex_text_parts.append(
                                f"  证据：{con.evidence}\n"
                            )
                # Build structured entity info for section_list
                entity_infos.append({
                    "id": entry.id,
                    "name": entry.name,
                    "type": entry.type,
                    "type_label": type_label,
                    "aliases": list(entry.aliases) if entry.aliases else [],
                    "body": body_text,
                    "revelations": [
                        {"chapter": r.chapter, "content": r.content, "source": r.source}
                        for r in entry.revelations
                    ],
                    "contradictions": [
                        {"chapter": c.chapter, "description": c.description,
                         "evidence": c.evidence, "resolved": c.resolved}
                        for c in entry.contradictions
                    ],
                    "is_placeholder": not entry.body.strip(),
                })
            if codex_truncated:
                codex_text_parts.append(
                    "（注：因 token 预算限制，部分设定条目已截断或省略）\n"
                )
            codex_text_parts.append("")
            codex_full = "".join(codex_text_parts)
            emit(codex_full)
            section_list.append(SectionInfo(
                key="codex",
                label="设定档案（必须严格遵守）",
                text=codex_full.split("\n", 1)[-1].strip(),
                tokens=_estimate_tokens(codex_full),
                entities=entity_infos,
            ))

        # --- 2. Big picture: synopsis + hierarchical memory -------------
        synopsis = self.outline.read_synopsis().strip()
        if synopsis:
            synopsis_text = (
                "## 全书梗概（开书前的原始规划，若与下方实际剧情冲突，以实际剧情为准）\n"
                f"{synopsis}\n\n"
            )
            emit(synopsis_text)
            section_list.append(SectionInfo(
                key="synopsis", label="全书梗概（原始规划）",
                text=synopsis, tokens=_estimate_tokens(synopsis),
            ))

        # 2a. Rolling story-so-far (coarse long-range memory).
        story_so_far, ssf_upto = self.outline.read_story_so_far()
        if story_so_far and ssf_upto < chapter.number:
            ssf_text = (
                f"## 全书至今的实际剧情（截至第 {ssf_upto} 章）\n"
                f"{story_so_far}\n\n"
            )
            emit(ssf_text)
            section_list.append(SectionInfo(
                key="story_so_far",
                label=f"全书至今的实际剧情（截至第 {ssf_upto} 章）",
                text=story_so_far,
                tokens=_estimate_tokens(story_so_far),
            ))

        # 2b. Completed-volume recaps (medium-grain memory).
        recaps = self._gather_volume_recaps(chapter)
        if recaps:
            recap_parts: list[str] = ["## 已完成卷的剧情回顾\n"]
            recap_items: list[dict] = []
            for vol_num, vol_title, recap in recaps:
                recap_parts.append(
                    f"### 第 {vol_num} 卷{f'《{vol_title}》' if vol_title else ''}\n{recap}\n"
                )
                recap_items.append({"volume": vol_num, "title": vol_title, "text": recap})
            recap_parts.append("")
            recap_full = "".join(recap_parts)
            emit(recap_full)
            section_list.append(SectionInfo(
                key="volume_recaps",
                label="已完成卷的剧情回顾",
                text="\n\n".join(r for _, _, r in recaps),
                tokens=_estimate_tokens(recap_full),
                sub_items=recap_items,
            ))

        # 2c. Current volume arc (planning-time).
        if chapter.volume:
            vol = self.outline.read_volume(chapter.volume)
            if vol and vol.arc:
                vol_text = (
                    f"## 本卷大纲（第 {vol.number} 卷：{vol.title or ''}）\n"
                    f"{vol.arc.strip()}\n\n"
                )
                emit(vol_text)
                section_list.append(SectionInfo(
                    key="volume",
                    label=f"本卷大纲（第 {vol.number} 卷：{vol.title or ''}）",
                    text=vol.arc.strip(),
                    tokens=_estimate_tokens(vol.arc),
                ))

        # --- 3. Recent chapter summaries -------------------------------
        summaries = self._gather_summaries(chapter.number)
        if summaries:
            summary_parts: list[str] = ["## 此前剧情摘要（按章节）\n"]
            summary_items: list[dict] = []
            for num, text in summaries:
                summary_parts.append(f"- 第 {num} 章：{text}\n")
                summary_items.append({"chapter": num, "text": text})
            summary_parts.append("")
            summary_full = "".join(summary_parts)
            emit(summary_full)
            section_list.append(SectionInfo(
                key="summaries", label="此前剧情摘要（按章节）",
                text="\n".join(
                    f"第 {num} 章：{text}" for num, text in summaries
                ),
                tokens=_estimate_tokens(summary_full),
                sub_items=summary_items,
            ))

        # --- 4. Recent full prose (sliding window; write mode only) ----
        recent = self.window.recent(
            self.generation.recent_window_chapters, before=chapter.number
        ) if for_writing else []
        if recent:
            prose_parts: list[str] = [
                "## 紧邻的前文（保持文风/人称/时态连贯）\n"
            ]
            for ch in recent:
                prose_parts.append(
                    f"--- 第 {ch.number} 章原文 ---\n{ch.text}\n\n"
                )
            prose_full = "".join(prose_parts)
            emit(prose_full)
            section_list.append(SectionInfo(
                key="recent_prose",
                label="紧邻的前文（保持文风/人称/时态连贯）",
                text=prose_full.split("\n", 1)[-1].strip(),
                tokens=_estimate_tokens(prose_full),
            ))
            self_recent_nums = [c.number for c in recent]
        else:
            self_recent_nums = []

        # --- 5. Entity current state -----------------------------------
        states = self.entity_state.get_many(entity_ids)
        states = [s for s in states if _state_nonempty(s)]
        if states:
            state_parts: list[str] = [
                "## 相关实体的当前状态（写作时必须与此一致）\n"
            ]
            state_items: list[dict] = []
            for s in states:
                formatted = self._format_state(s)
                state_parts.append(formatted)
                state_items.append(_state_to_dict(s))
            state_parts.append("")
            state_full = "".join(state_parts)
            emit(state_full)
            section_list.append(SectionInfo(
                key="entity_state",
                label="相关实体的当前状态（写作时必须与此一致）",
                text="\n".join(
                    _state_one_line(si) for si in state_items
                ),
                tokens=_estimate_tokens(state_full),
                sub_items=state_items,
            ))

        # --- 6. Open plot threads (foreshadowing / suspense) ------------
        try:
            open_threads = self.threads.format_open_threads(
                upto_chapter=chapter.number
            )
        except Exception:
            open_threads = ""
        if open_threads:
            threads_text = (
                "## 未回收的情节线索（伏笔/悬念，不得遗忘或提前泄底）\n"
                f"{open_threads}\n\n"
            )
            emit(threads_text)
            section_list.append(SectionInfo(
                key="threads",
                label="未回收的情节线索",
                text=open_threads,
                tokens=_estimate_tokens(threads_text),
            ))

        # --- 7. The chapter beat itself --------------------------------
        beat_text = self._format_beat(chapter)
        beat_full = (
            f"## 本章任务（基调渗透、细场景演出；禁止复述清单）\n{beat_text}"
        )
        emit(beat_full)
        section_list.append(SectionInfo(
            key="beat",
            label="本章任务（必须按此推进剧情）",
            text=beat_text.strip(),
            tokens=_estimate_tokens(beat_full),
        ))

        text = "\n".join(sections)
        return AssembledContext(
            text=text,
            sections={s.key: s.text for s in section_list},
            section_list=section_list,
            codex_used=codex_entries,
            entity_states_used=states,
            recent_chapters=self_recent_nums,
        )

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------
    def _gather_codex(
        self,
        entity_ids: list[str],
        chapter: ChapterOutline,
    ) -> tuple[list[CodexEntry], bool]:
        """Gather relevant codex entries within a token budget.

        Returns ``(entries, truncated)`` where *entries* may have their bodies
        truncated to fit the budget, and *truncated* is True if any truncation
        or dropping occurred.

        Priority (lowest priority number = included first):
          0 — explicitly referenced by a scene beat (most specific);
          1 — chapter-level entity ids;
          2 — matched by chapter tags;
          3 — vector-retrieval supplements (least specific).
        """
        from .token_budget import BudgetAllocator, BudgetedItem, truncate_to_chars

        # ---- collect candidates with priorities ----
        seen: set[str] = set()
        candidates: list[tuple[int, CodexEntry]] = []  # (priority, entry)

        beat_entities = {e for b in chapter.beats for e in b.entities}

        # 0 + 1: explicit ids. Beat-referenced ones outrank chapter-level ones.
        for eid in entity_ids:
            try:
                entry = self.codex.read(eid)
            except FileNotFoundError:
                continue
            if entry.id in seen:
                continue
            seen.add(entry.id)
            prio = 0 if eid in beat_entities else 1
            candidates.append((prio, entry))

        # 2: tag matches.
        tagset = set(chapter.tags)
        if tagset:
            for entry in self.codex.iter_all():
                if entry.id in seen:
                    continue
                if tagset & set(entry.tags):
                    seen.add(entry.id)
                    candidates.append((2, entry))

        # 3: optional vector supplement.
        if self.retriever is not None:
            probe = self._beat_probe(chapter)
            if probe:
                try:
                    hits = self.retriever.query(probe, k=6)
                except Exception:
                    hits = []
                for hit in hits:
                    hid = hit["id"]
                    if hid in seen:
                        continue
                    extra_list = self.codex.get_many([hid])
                    for entry in extra_list:
                        if entry.id in seen:
                            continue
                        seen.add(entry.id)
                        candidates.append((3, entry))

        # ---- allocate budget ----
        allocator = BudgetAllocator(
            budget_tokens=self.generation.codex_max_tokens,
            max_chars_per_item=self.generation.codex_entry_max_chars,
        )
        result: list[CodexEntry] = []
        truncated = False
        # Stable sort by priority (beat > chapter > tag > vector).
        for prio, entry in sorted(candidates, key=lambda c: c[0]):
            body = entry.body.strip()
            if not body:
                # Placeholder entry (auto-created) — include a 1-line stub so
                # the model at least knows the entity exists by name/type.
                body = "（档案待补：此实体由系统自动创建，暂无静态档案。）"
            item = BudgetedItem(
                key=entry.id,
                text=body,
                priority=prio,
                min_chars=200,
            )
            chosen = allocator.try_add(item)
            if chosen is None:
                truncated = True
                continue
            if len(chosen) < len(body):
                truncated = True
            # Return a shallow copy with the (possibly truncated) body.
            result.append(
                CodexEntry(
                    id=entry.id,
                    name=entry.name,
                    type=entry.type,
                    aliases=entry.aliases,
                    tags=entry.tags,
                    related=entry.related,
                    revelations=list(entry.revelations),
                    contradictions=list(entry.contradictions),
                    relationships=list(entry.relationships),
                    body=chosen,
                )
            )
        return result, truncated

    def _gather_summaries(self, current_number: int) -> list[tuple[int, str]]:
        """Return the most recent N chapter summaries before *current_number*."""
        chapters = self.outline.list_chapters()
        candidates = [
            c for c in chapters if c.number < current_number and c.summary.strip()
        ]
        candidates.sort(key=lambda c: c.number, reverse=True)
        keep = candidates[: self.generation.summary_history]
        keep.sort(key=lambda c: c.number)
        out: list[tuple[int, str]] = []
        for c in keep:
            text = c.summary.strip()
            if c.story_date:
                text = f"（{c.story_date}）{text}"
            out.append((c.number, text))
        return out

    def _gather_volume_recaps(
        self, chapter: ChapterOutline
    ) -> list[tuple[int, str, str]]:
        """Recaps of volumes that precede the chapter's volume.

        Returns ``(number, title, recap)`` tuples for earlier volumes that
        have a realized recap — the medium-grain layer between the coarse
        story-so-far and the fine recent chapter summaries.
        """
        current_vol = chapter.volume
        out: list[tuple[int, str, str]] = []
        for vol in self.outline.list_volumes():
            if not vol.recap.strip():
                continue
            if current_vol is not None and vol.number >= current_vol:
                continue
            out.append((vol.number, vol.title or "", vol.recap.strip()))
        out.sort(key=lambda v: v[0])
        return out

    def _format_beat(self, chapter: ChapterOutline) -> str:
        lines: list[str] = []
        if chapter.title:
            lines.append(f"章节标题：{chapter.title}")
        if chapter.volume:
            lines.append(f"所属卷：第 {chapter.volume} 卷")
        if chapter.purpose:
            lines.append(f"本章叙事功能：{chapter.purpose}")
        if chapter.value_shift:
            lines.append(f"情感价值转变：{chapter.value_shift}")
        if chapter.tension:
            lines.append(f"张力等级：{chapter.tension}/5")
        if chapter.story_date:
            line = f"故事内时间：{chapter.story_date}"
            if chapter.elapsed:
                line += f"（距上一章：{chapter.elapsed}）"
            lines.append(line)

        if chapter.keynote:
            lines.append("")
            lines.append("【章基调 — 必须渗透进剧情，禁止在正文中明说或总结】")
            for k in chapter.keynote:
                lines.append(f"- {k}")
            lines.append("")

        has_micro = any(b.scenes for b in chapter.beats)
        if chapter.beats and has_micro:
            lines.append("细场景计划（按此推进体验，禁止逐条复述目标/结果）：")
            for i, b in enumerate(chapter.beats, 1):
                anchor = b.goal or f"场景{i}"
                lines.append(f"  Beat {i}｜锚点：{anchor}")
                if b.conflict:
                    lines.append(f"    （冲突：{b.conflict}）")
                for j, s in enumerate(b.scenes, 1):
                    meta_bits = []
                    if s.words:
                        meta_bits.append(f"约{s.words}字")
                    if s.pacing:
                        meta_bits.append(s.pacing)
                    if s.technique:
                        meta_bits.append(s.technique)
                    meta = "·".join(meta_bits) if meta_bits else ""
                    intent = (s.intent or s.event or s.action or "").strip()
                    head = f"    {j}{'（' + meta + '）' if meta else ''}："
                    lines.append(f"{head}{intent}" if intent else head)
                    if s.sensory:
                        lines.append(f"      感官/氛围：{s.sensory}")
                    if s.action:
                        lines.append(f"      动作：{s.action}")
                    if s.dialogue:
                        lines.append(f"      对白方向：{s.dialogue}")
                    if s.event and s.event.strip() != intent:
                        lines.append(f"      事件：{s.event}")
                if b.entities:
                    lines.append(f"    涉及：{'、'.join(b.entities)}")
        elif chapter.beats:
            lines.append("场景计划：")
            for i, b in enumerate(chapter.beats, 1):
                lines.append(f"  场景{i}：")
                lines.append(f"    目标：{b.goal}")
                if b.conflict:
                    lines.append(f"    冲突：{b.conflict}")
                if b.outcome:
                    lines.append(f"    结果：{b.outcome}")
                if b.entities:
                    lines.append(f"    涉及：{'、'.join(b.entities)}")
        else:
            lines.append("（本章未提供具体场景计划，请在保持前文一致的前提下合理推进剧情。）")
        if chapter.hook:
            lines.append(f"章末钩子（结尾必须留下）：{chapter.hook}")
        if chapter.notes:
            lines.append("")
            lines.append(f"作者附注：\n{chapter.notes.strip()}")
        return "\n".join(lines) + "\n"

    def _format_state(self, s: EntityState) -> str:
        lines = [f"- [{s.entity_id}]"]
        if s.location:
            lines.append(f"    当前位置：{s.location}")
        if s.status:
            lines.append(f"    当前状态：{s.status}")
        if s.knowledge:
            knowledge_text = "；".join(
                k.fact if hasattr(k, 'fact') else str(k) for k in s.knowledge
            )
            lines.append(f"    已知信息：{knowledge_text}")
        if s.possessions:
            possession_text = "、".join(
                p.item if hasattr(p, 'item') else str(p) for p in s.possessions
            )
            lines.append(f"    随身物品：{possession_text}")
        if s.relationships:
            rels = "、".join(f"{k}({v})" for k, v in s.relationships.items())
            lines.append(f"    人际关系：{rels}")
        lines.append(f"    最后出现于第 {s.last_seen_chapter} 章")
        return "\n".join(lines) + "\n"

    def _beat_probe(self, chapter: ChapterOutline) -> str:
        parts = [b.goal for b in chapter.beats if b.goal]
        if chapter.title:
            parts.insert(0, chapter.title)
        return " ".join(parts)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
_TYPE_LABELS = {
    "character": "实体",
    "worldbuilding": "世界观",
    "location": "地点",
    "faction": "势力",
    "item": "物品",
    "timeline": "时间线",
}


def _type_label(t: str) -> str:
    return _TYPE_LABELS.get(t, t)


def _demote_headings(text: str) -> str:
    """Demote markdown headings by one level so body content nests correctly.

    ``## 外貌`` → ``### 外貌``, ``# 背景`` → ``## 背景``.
    This prevents body-internal headings from being parsed as context sections.
    """
    import re
    return re.sub(r"^(#+)(\s)", lambda m: "#" + m.group(1) + m.group(2), text, flags=re.MULTILINE)


def _state_nonempty(s: EntityState) -> bool:
    return any(
        [
            s.location,
            s.status,
            s.knowledge,
            s.possessions,
            s.relationships,
            s.last_seen_chapter > 0,
        ]
    )


def _state_to_dict(s: EntityState) -> dict:
    """Convert an EntityState to a JSON-serialisable dict for structured display."""
    return {
        "entity_id": s.entity_id,
        "location": s.location or "",
        "status": s.status or "",
        "knowledge": [
            k.fact if hasattr(k, 'fact') else str(k)
            for k in s.knowledge
        ],
        "possessions": [
            p.item if hasattr(p, 'item') else str(p)
            for p in s.possessions
        ],
        "relationships": dict(s.relationships) if s.relationships else {},
        "last_seen_chapter": s.last_seen_chapter,
    }


def _state_one_line(si: dict) -> str:
    """One-line summary of an entity state dict, never empty."""
    parts = [si["entity_id"]]
    if si["status"]:
        parts.append(f"状态:{si['status']}")
    if si["location"]:
        parts.append(f"@{si['location']}")
    return " ".join(parts)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: CJK ~1.5 chars/token, ASCII ~4 chars/token."""
    cjk = 0
    ascii_chars = 0
    for ch in text:
        cp = ord(ch)
        if (
            (0x3040 <= cp <= 0x30FF)
            or (0x3400 <= cp <= 0x9FFF)
            or (0xFF00 <= cp <= 0xFFEF)
            or cp > 127
        ):
            cjk += 1
        else:
            ascii_chars += 1
    return max(1, int(cjk / 1.5 + ascii_chars / 4))


# ---------------------------------------------------------------------------
# Write-time context snapshots
# ---------------------------------------------------------------------------
def serialize_context(ctx: AssembledContext) -> dict:
    """JSON-safe dict of an assembled context (for disk / API)."""
    section_list: list[dict] = []
    for sec in ctx.section_list:
        d: dict = {
            "key": sec.key,
            "label": sec.label,
            "text": sec.text,
            "tokens": sec.tokens,
        }
        if sec.entities:
            d["entities"] = sec.entities
        if sec.sub_items:
            d["sub_items"] = sec.sub_items
        section_list.append(d)
    return {
        "text": ctx.text,
        "section_list": section_list,
        "codex_used": [e.id for e in ctx.codex_used],
        "entity_states": [s.entity_id for s in ctx.entity_states_used],
        "recent_chapters": list(ctx.recent_chapters),
    }


def save_context_snapshot(paths: ProjectPaths, number: int, ctx: AssembledContext) -> Path:
    """Persist the write-time context next to the draft file."""
    import json
    from ..versioning import atomic_write

    path = paths.context_snapshot_file(number)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_context(ctx)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def load_context_snapshot(paths: ProjectPaths, number: int) -> dict | None:
    """Load a previously saved write-time context, or ``None`` if missing."""
    import json

    path = paths.context_snapshot_file(number)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
