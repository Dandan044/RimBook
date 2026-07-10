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

    def __init__(self, llm: LLMClient, prompts: Prompts, outline: OutlineStore) -> None:
        self.llm = llm
        self.prompts = prompts
        self.outline = outline

    def summarize(self, chapter_number: int, chapter_text: str) -> str:
        """Generate and persist a summary for a written chapter."""
        messages = self.llm.as_chat(
            system=self.prompts.summarize_system,
            user=(
                f"这是第 {chapter_number} 章的正文，请生成章节摘要。\n\n"
                f"---\n{chapter_text}\n"
            ),
        )
        result = self.llm.generate(
            messages,
            temperature=0.3,
            model=self.llm.config.effective_check_model,
        )
        summary = result.content.strip()
        # Persist back into the chapter outline file.
        self.outline.update_chapter_summary(chapter_number, summary)
        return summary

    def extract_entity_deltas(
        self,
        chapter_number: int,
        chapter_text: str,
        entity_ids: list[str],
    ) -> list[EntityDelta]:
        """Ask the model how each entity's state changed during the chapter."""
        if not entity_ids:
            return []
        messages = self.llm.as_chat(
            system=(
                "你是精确的小说状态跟踪助手。阅读章节正文，针对每个指定实体，"
                "判断其在『本章之后』的当前状态变化，并输出 JSON。\n"
                "只包含发生了变化或需要记录的字段；未变化的字段省略或留空。\n"
                "【生命周期规则 —— 重要】\n"
                "- knowledge/possessions 表示『本章新获得』的信息/物品；\n"
                "- knowledge_remove/possessions_remove 表示『本章遗忘/丢失』的信息/物品；\n"
                "- relationships 为 {对方id: 关系简述}；若关系终结/破裂，将值设为 null；\n"
                "- location/status 为本章结束时的最新值（会覆盖前值）。\n"
                "角色丢失物品、遗忘信息、关系破裂都必须如实记录到对应的 remove / null 字段。"
            ),
            user=(
                f"第 {chapter_number} 章正文：\n---\n{chapter_text}\n---\n\n"
                f"需要跟踪的实体 id：{entity_ids}\n\n"
                "请输出 JSON，格式为：\n"
                '{\n'
                '  "entities": [\n'
                '    {\n'
                '      "entity_id": "...",\n'
                '      "location": "...",\n'
                '      "status": "...",\n'
                '      "knowledge": ["新获得的信息"],\n'
                '      "possessions": ["新获得的物品"],\n'
                '      "knowledge_remove": ["遗忘/过时的信息"],\n'
                '      "possessions_remove": ["丢失/消耗的物品"],\n'
                '      "relationships": {"id": "关系", "结束的id": null}\n'
                '    }\n'
                '  ]\n'
                '}\n'
                "只输出 JSON。"
            ),
        )
        data = self.llm.generate_json(
            messages,
            model=self.llm.config.effective_check_model,
            temperature=0.0,
        )
        return _parse_deltas(data, entity_ids)

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
def _parse_deltas(data: dict[str, Any], entity_ids: list[str]) -> list[EntityDelta]:
    raw = data.get("entities") or []
    out: list[EntityDelta] = []
    known = set(entity_ids)
    for item in raw:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("entity_id") or "").strip()
        if not eid:
            continue
        # Only accept ids we asked about, to avoid hallucinated entities.
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
