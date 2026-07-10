"""Context assembly — the single most important component in RimBook.

On every generation, instead of dumping an entire novel into the prompt, we
assemble a small, carefully layered context that contains *exactly* what the
model needs to write the current chapter consistently:

1. Relevant codex entries (explicit via the chapter's entity ids/tags,
   supplemented by optional vector retrieval),
2. The synopsis + relevant volume summaries (the big picture),
3. Recent chapter *summaries* (what happened before),
4. A sliding window of recent *full prose* (voice/tense continuity),
5. The *current* state of every entity involved (anti-OOC),
6. The chapter beat itself (what must happen now).

The result is a single :class:`AssembledContext` string + token estimate,
ready to feed to the writer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..codex import CodexEntry, CodexStore
from ..config import GenerationConfig
from ..outline import ChapterOutline, OutlineStore
from ..project import ProjectPaths
from .entity_state import EntityState, EntityStateStore
from .window import SlidingWindow

__all__ = ["ContextAssembler", "AssembledContext"]


@dataclass
class AssembledContext:
    """The fully assembled prompt context for one generation."""

    text: str
    sections: dict[str, str] = field(default_factory=dict)
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
    ) -> None:
        self.paths = paths
        self.codex = codex
        self.outline = outline
        self.entity_state = entity_state
        self.window = window
        self.generation = generation
        self.retriever = retriever

    def assemble_for_chapter(self, chapter: ChapterOutline) -> AssembledContext:
        """Assemble context for writing the given chapter outline."""
        sections: list[str] = []
        emit = sections.append  # local alias

        # --- 1. Relevant codex entries ---------------------------------
        entity_ids = chapter.all_entities()
        codex_entries, codex_truncated = self._gather_codex(entity_ids, chapter)
        if codex_entries:
            emit("## 设定档案（必须严格遵守）\n")
            for entry in codex_entries:
                emit(f"### [{_type_label(entry.type)}] {entry.name}（id: {entry.id}）\n")
                if entry.aliases:
                    emit(f"别名：{'、'.join(entry.aliases)}\n")
                emit(entry.body.strip() + "\n")
            if codex_truncated:
                emit(f"（注：因 token 预算限制，部分设定条目已截断或省略）\n")
            emit("")

        # --- 2. Synopsis + volume summary ------------------------------
        synopsis = self.outline.read_synopsis().strip()
        if synopsis:
            emit("## 全书梗概\n")
            emit(synopsis + "\n\n")
        if chapter.volume:
            vol = self.outline.read_volume(chapter.volume)
            if vol and vol.arc:
                emit(f"## 本卷大纲（第 {vol.number} 卷：{vol.title or ''}）\n")
                emit(vol.arc.strip() + "\n\n")

        # --- 3. Recent chapter summaries -------------------------------
        summaries = self._gather_summaries(chapter.number)
        if summaries:
            emit("## 此前剧情摘要（按章节）\n")
            for num, text in summaries:
                emit(f"- 第 {num} 章：{text}\n")
            emit("")

        # --- 4. Recent full prose (sliding window) ---------------------
        recent = self.window.recent(
            self.generation.recent_window_chapters, before=chapter.number
        )
        if recent:
            emit("## 紧邻的前文（保持文风/人称/时态连贯）\n")
            for ch in recent:
                emit(f"--- 第 {ch.number} 章原文 ---\n{ch.text}\n\n")
            self_recent_nums = [c.number for c in recent]
        else:
            self_recent_nums = []

        # --- 5. Entity current state -----------------------------------
        states = self.entity_state.get_many(entity_ids)
        states = [s for s in states if _state_nonempty(s)]
        if states:
            emit("## 相关实体的当前状态（写作时必须与此一致）\n")
            for s in states:
                emit(self._format_state(s))
            emit("")

        # --- 6. The chapter beat itself --------------------------------
        emit("## 本章任务（必须按此推进剧情）\n")
        emit(self._format_beat(chapter))
        emit("")

        text = "\n".join(sections)
        return AssembledContext(
            text=text,
            sections={},  # not segmented further; sections are inline above
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
        return [(c.number, c.summary.strip()) for c in keep]

    def _format_beat(self, chapter: ChapterOutline) -> str:
        lines: list[str] = []
        if chapter.title:
            lines.append(f"章节标题：{chapter.title}")
        if chapter.volume:
            lines.append(f"所属卷：第 {chapter.volume} 卷")
        if chapter.beats:
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
            lines.append(f"    已知信息：{'；'.join(s.knowledge)}")
        if s.possessions:
            lines.append(f"    随身物品：{'、'.join(s.possessions)}")
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
