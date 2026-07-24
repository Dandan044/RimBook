"""Merge and prompt-context services for the author-side planning codex."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..codex.models import VALID_TYPES
from .completeness import incomplete_entry_fields
from .identity import NameRegistry
from .models import (
    PlanningCodexChanges,
    PlanningCodexEntry,
    PlanningCodexProposal,
    PlanningRelationship,
    RelationshipProposal,
)
from .store import PlanningCodexStore

if TYPE_CHECKING:
    from ..codex.store import CodexStore

__all__ = ["PlanningCodexService", "EntityNetworkService", "ReconcileResult"]


@dataclass
class ReconcileResult:
    """A small, serializable summary of a codex reconciliation."""

    created_entries: list[str] = field(default_factory=list)
    updated_entries: list[str] = field(default_factory=list)
    created_relationships: list[str] = field(default_factory=list)
    updated_relationships: list[str] = field(default_factory=list)
    skipped_locked_fields: list[str] = field(default_factory=list)
    skipped_relationships: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Legacy aliases
    @property
    def created_entities(self) -> list[str]:
        return self.created_entries

    @property
    def updated_entities(self) -> list[str]:
        return self.updated_entries

    @property
    def change_count(self) -> int:
        return sum(
            len(values)
            for values in (
                self.created_entries,
                self.updated_entries,
                self.created_relationships,
                self.updated_relationships,
            )
        )

    def model_dump(self) -> dict[str, object]:
        return {
            "created_entries": self.created_entries,
            "updated_entries": self.updated_entries,
            "created_relationships": self.created_relationships,
            "updated_relationships": self.updated_relationships,
            "created_entities": self.created_entries,
            "updated_entities": self.updated_entries,
            "skipped_locked_fields": self.skipped_locked_fields,
            "skipped_relationships": self.skipped_relationships,
            "warnings": self.warnings,
            "change_count": self.change_count,
        }


_TYPE_LABELS = {
    "character": "角色",
    "worldbuilding": "世界观",
    "location": "地点",
    "faction": "势力",
    "item": "物品",
    "timeline": "时间线",
}

DETAIL_TYPE_ORDER = (
    "worldbuilding",
    "timeline",
    "faction",
    "location",
    "character",
    "item",
)

# When truncating render_full, keep higher-priority types first.
_FULL_RENDER_KEEP_PRIORITY = (
    "character",
    "location",
    "faction",
    "worldbuilding",
    "item",
    "timeline",
)


class PlanningCodexService:
    """Applies AI proposals safely and renders compact planning context."""

    def __init__(self, store: PlanningCodexStore) -> None:
        self.store = store

    def reconcile(self, changes: PlanningCodexChanges, *, source: str) -> ReconcileResult:
        """Merge proposed changes while preserving every explicitly locked field."""
        result = ReconcileResult()
        entries = {e.id: e for e in self.store.list_entries()}
        relationships = {r.id: r for r in self.store.list_relationships()}
        registry = NameRegistry.from_entries(entries.values())

        for proposal in changes.entries:
            existing = entries.get(proposal.id)
            if existing is None:
                entry_type = (proposal.type or "").strip()
                if entry_type not in VALID_TYPES:
                    result.warnings.append(
                        f"跳过新建 {proposal.id}：缺少有效 type"
                        f"（得到 {proposal.type!r}），需先补全字段"
                    )
                    continue
                proposed_name = (proposal.name or "").strip()
                if not proposed_name:
                    result.warnings.append(f"跳过新建 {proposal.id}：缺少 name")
                    continue
                if proposed_name:
                    match_id = registry.find_match(proposed_name, entry_type)
                    if match_id:
                        existing = entries[match_id]
                        result.warnings.append(
                            f"名称“{proposed_name}”与已有 {match_id} 匹配，"
                            f"已合并提案 {proposal.id} 而非新建"
                        )
                        # Preserve alternate id/name as aliases on the canonical entry
                        extra_aliases = [
                            value
                            for value in (proposed_name, proposal.id)
                            if value
                            and value != existing.name
                            and value not in existing.aliases
                            and value != match_id
                        ]
                        merge_proposal = proposal.model_copy(update={"id": match_id})
                        if extra_aliases:
                            merged_aliases = list(
                                dict.fromkeys(
                                    [
                                        *(existing.aliases or []),
                                        *(proposal.aliases or []),
                                        *extra_aliases,
                                    ]
                                )
                            )
                            merge_proposal = merge_proposal.model_copy(
                                update={"aliases": merged_aliases}
                            )
                        if self._merge_entry(existing, merge_proposal, result):
                            existing.source = source
                            self.store.save_entry(existing)
                            result.updated_entries.append(existing.id)
                        registry.add_entry(existing)
                        continue
                    # Cross-type name collision: refuse create
                    cross = [
                        owner
                        for owner in registry.owners_of(proposed_name)
                        if owner.entry_type != entry_type
                    ]
                    if cross:
                        owner = cross[0]
                        result.warnings.append(
                            f"跳过新建 {proposal.id}（{proposed_name}）："
                            f"姓名已被 {owner.entry_id}（{owner.display}/"
                            f"{owner.entry_type}）占用"
                        )
                        continue
                entry = self._new_entry(proposal, source)
                self.store.save_entry(entry)
                entries[entry.id] = entry
                registry.add_entry(entry)
                result.created_entries.append(entry.id)
                continue
            if self._merge_entry(existing, proposal, result):
                existing.source = source
                self.store.save_entry(existing)
                result.updated_entries.append(existing.id)
                registry.add_entry(existing)

        for proposal in changes.relationships:
            existing = relationships.get(proposal.id)
            if existing is None:
                relationship = self._new_relationship(proposal, source)
                if relationship is None or not self._relationship_endpoints_exist(relationship, entries):
                    result.skipped_relationships.append(proposal.id)
                    continue
                self.store.save_relationship(relationship)
                relationships[relationship.id] = relationship
                result.created_relationships.append(relationship.id)
                continue
            proposed_endpoints = (
                proposal.resolved_source_id(existing.source_id) or existing.source_id,
                proposal.resolved_target_id(existing.target_id) or existing.target_id,
            )
            if any(endpoint not in entries for endpoint in proposed_endpoints):
                result.skipped_relationships.append(proposal.id)
                continue
            if self._merge_relationship(existing, proposal, result):
                existing.source = source
                self.store.save_relationship(existing)
                result.updated_relationships.append(existing.id)

        return result

    def apply_foundation_entries(
        self,
        raw_entries: list[dict],
        *,
        source: str = "foundation",
        require_existence: bool = False,
    ) -> ReconcileResult:
        """Import rough entries one-by-one and enforce story-anchor existence.

        When ``require_existence`` is true, candidates must explicitly assert
        ``exists_at_anchor=true``. A future-created existence may instead
        provide ``formation_event``; only that timeline event is persisted.
        """
        result = ReconcileResult()
        proposals: list[PlanningCodexProposal] = []
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            # Safety net: never invent type=character for blank type.
            missing = incomplete_entry_fields(
                item, require_existence=require_existence,
            )
            # Allow exists_at_anchor=false path to proceed even if formation
            # fields are being rewritten below; still require id/name/type.
            critical = [f for f in missing if f in {"id", "name", "type"}]
            if critical:
                result.warnings.append(
                    f"跳过不完整设定 {item.get('id', '?')}：缺少 {', '.join(critical)}"
                )
                continue
            if require_existence and item.get("exists_at_anchor") is not True:
                if item.get("type") == "timeline":
                    payload = {
                        key: value
                        for key, value in item.items()
                        if key not in {
                            "exists_at_anchor",
                            "existence_reason",
                            "formation_event",
                        }
                    }
                    details = dict(payload.get("details") or {})
                    details.setdefault("event_status", "planned")
                    payload["details"] = details
                    try:
                        proposals.append(
                            PlanningCodexProposal.model_validate(payload)
                        )
                        result.warnings.append(
                            f"{item.get('name') or item.get('id')}尚未发生，"
                            "已作为 planned 时间线事件保留"
                        )
                    except Exception:
                        result.warnings.append(
                            f"跳过无效未来时间线事件: {item.get('id', '?')}"
                        )
                    continue
                event = self._formation_event_proposal(item)
                if event is not None:
                    proposals.append(event)
                    result.warnings.append(
                        f"{item.get('name') or item.get('id') or '未命名设定'}尚未存在，"
                        f"已仅记录其成立事件 {event.id}"
                    )
                else:
                    result.warnings.append(
                        f"跳过尚未在故事锚点存在的设定: {item.get('id', '?')}"
                    )
                continue
            try:
                payload = {
                    key: value
                    for key, value in item.items()
                    if key not in {"exists_at_anchor", "existence_reason", "formation_event"}
                }
                proposals.append(PlanningCodexProposal.model_validate(payload))
            except Exception:
                result.warnings.append(f"跳过无效设定条目: {item.get('id', '?')}")
        reconciled = self.reconcile(
            PlanningCodexChanges(entries=proposals),
            source=source,
        )
        reconciled.warnings[:0] = result.warnings
        return reconciled

    @staticmethod
    def _formation_event_proposal(item: dict) -> PlanningCodexProposal | None:
        raw = item.get("formation_event")
        if not raw:
            return None
        original_id = str(item.get("id") or "future_existence").strip()
        original_name = str(item.get("name") or original_id).strip()
        if isinstance(raw, str):
            event_id = f"evt_{original_id.removeprefix('evt_')}_formation"
            name = f"{original_name}的成立"
            summary = raw.strip()
            detail = ""
        elif isinstance(raw, dict):
            event_id = str(raw.get("id") or f"evt_{original_id}_formation").strip()
            name = str(raw.get("name") or f"{original_name}的成立").strip()
            summary = str(raw.get("surface_summary") or raw.get("description") or "").strip()
            detail = str(raw.get("detail") or "").strip()
        else:
            return None
        if not event_id or not name or not summary:
            return None
        return PlanningCodexProposal(
            id=event_id,
            name=name,
            type="timeline",
            surface_summary=summary,
            narrative_role=f"记录{original_name}从不存在到成立的剧情事件",
            reveal_strategy="随成立事件在正文中发生而首次呈现",
            detail=detail,
            details={
                "event_kind": "formation",
                "event_status": "planned",
                "future_entry_id": original_id,
                "future_entry_type": str(item.get("type") or ""),
            },
        )

    def entries_needing_detail(
        self,
        *,
        entry_type: str | None = None,
        entry_ids: list[str] | None = None,
    ) -> list[PlanningCodexEntry]:
        wanted = set(entry_ids or [])
        return [
            entry
            for entry in self.store.list_entries(entry_type)
            if (not wanted or entry.id in wanted) and not entry.detail.strip()
        ]

    def apply_detail(
        self,
        entry_id: str,
        *,
        detail: str,
        details_patch: dict | None = None,
        source: str = "detail_generation",
    ) -> ReconcileResult:
        """Merge one generated long-form detail and its structured extraction."""
        entry = self.store.get_entry(entry_id)
        normalized_patch = self._normalize_details_patch(
            entry.type,
            dict(details_patch or {}),
        )
        proposal = PlanningCodexProposal(
            id=entry_id,
            detail=detail.strip(),
            details=normalized_patch,
        )
        return self.reconcile(
            PlanningCodexChanges(entries=[proposal]),
            source=source,
        )

    @staticmethod
    def _normalize_details_patch(
        entry_type: str,
        details_patch: dict,
    ) -> dict:
        """Normalize common localized LLM keys to stable machine fields."""
        if entry_type != "character":
            return details_patch
        aliases = {
            "深层需求": "inner_need",
            "内在需求": "inner_need",
            "核心欲望": "inner_need",
            "欲望": "inner_need",
            "恐惧": "fear",
            "核心恐惧": "fear",
            "缺陷": "flaw",
            "核心缺陷": "flaw",
            "价值观": "values",
            "观点": "values",
            "能力": "capabilities",
            "关键技能": "capabilities",
            "限制": "limitations",
            "盲区": "limitations",
            "说话方式": "voice",
            "声音与语言": "voice",
            "行动习惯": "action_style",
            "行动方式": "action_style",
            "关键经历": "key_experiences",
        }
        normalized = dict(details_patch)
        for raw_key, canonical in aliases.items():
            if raw_key not in normalized:
                continue
            if canonical not in normalized or not normalized[canonical]:
                normalized[canonical] = normalized[raw_key]
            if raw_key != canonical:
                normalized.pop(raw_key, None)
        return normalized

    def render_detail_context(
        self,
        entry_id: str,
        *,
        synopsis: str,
        max_related: int = 10,
        max_chars: int = 14000,
    ) -> str:
        """Build bounded context from world rules, upstream details and relations."""
        target = self.store.get_entry(entry_id)
        all_entries = self.store.list_entries()
        by_id = {entry.id: entry for entry in all_entries}
        relations = self.store.list_relationships()
        related_ids: list[str] = []
        relation_lines: list[str] = []
        for relation in relations:
            if relation.source_id == entry_id:
                related_ids.append(relation.target_id)
            elif relation.target_id == entry_id:
                related_ids.append(relation.source_id)
            else:
                continue
            relation_lines.append(
                f"- {relation.source_id} → {relation.target_id}"
                f"（{relation.relationship_type}）："
                f"{relation.conflict or relation.stakes or relation.status or '有关联'}"
            )

        upstream_rank = DETAIL_TYPE_ORDER.index(target.type)
        candidates: list[PlanningCodexEntry] = []
        # Worldbuilding is an implicit parent of every entry.
        candidates.extend(
            entry for entry in all_entries
            if entry.type == "worldbuilding" and entry.id != entry_id
        )
        candidates.extend(
            by_id[rid] for rid in related_ids
            if rid in by_id and rid != entry_id
        )
        candidates.extend(
            entry for entry in all_entries
            if entry.id != entry_id
            and entry.type in DETAIL_TYPE_ORDER[:upstream_rank]
            and entry.detail
        )

        unique: list[PlanningCodexEntry] = []
        seen: set[str] = set()
        for entry in candidates:
            if entry.id in seen:
                continue
            seen.add(entry.id)
            unique.append(entry)
            if len(unique) >= max_related:
                break

        blocks = [
            f"【宏观梗概】\n{synopsis.strip()}",
            "【当前待细化条目】\n"
            f"id: {target.id}\n名称: {target.name}\n类型: {target.type}\n"
            f"公开面: {target.surface_summary or '待定'}\n"
            f"叙事职责: {target.narrative_role or '待定'}\n"
            f"幕后真相: {target.secret_truth or '无'}\n"
            f"首次登场方式: {target.reveal_strategy or '待定'}\n"
            f"结构化细节: {target.details or {}}",
        ]
        planned_events = [
            entry
            for entry in all_entries
            if entry.type == "timeline"
            and entry.details.get("event_status") == "planned"
        ]
        if planned_events:
            blocks.append(
                "【尚未发生的事件——绝不可写成既成事实】\n"
                + "\n".join(
                    f"- {entry.id}（{entry.name}）："
                    f"{entry.surface_summary or '仅为未来计划'}"
                    for entry in planned_events
                )
            )
        if relation_lines:
            blocks.append("【显式关系】\n" + "\n".join(relation_lines))
        if unique:
            lines = ["【相关与上游设定】"]
            for entry in unique:
                excerpt = (entry.detail or entry.surface_summary or entry.secret_truth)[:1200]
                lines.append(
                    f"- [{entry.type}] {entry.id}（{entry.name}）：{excerpt or '仅有粗略设定'}"
                )
            blocks.append("\n".join(lines))
        occupied = NameRegistry.from_entries(all_entries).render_occupied_block(
            max_chars=2200,
        )
        blocks.append(occupied)
        return "\n\n".join(blocks)[:max_chars]

    def detail_quality_issues(
        self,
        entry_id: str,
        detail: str,
    ) -> list[str]:
        """Apply deterministic quality gates before a generated detail is saved."""
        issues: list[str] = []
        target = self.store.get_entry(entry_id)
        if len(detail) < 240:
            issues.append(f"详情过短（{len(detail)} 字符）")
        if detail.count("\n") < 2:
            issues.append("缺少分段与时间/因果层次")
        for heading in ("未来走向", "未来发展", "结局走向"):
            if heading in detail:
                issues.append(f"包含超出故事锚点的章节“{heading}”")
        if (
            target.type == "timeline"
            and target.details.get("event_status") == "planned"
        ):
            if "尚未发生" not in detail:
                issues.append("planned 时间线未明确标注“尚未发生”")
            for phrase in ("已完成", "已满足", "已经完成", "已经满足"):
                if phrase in detail:
                    issues.append(f"planned 时间线把未来条件写成既成事实：“{phrase}”")

        planned = [
            entry
            for entry in self.store.list_entries("timeline")
            if entry.details.get("event_status") == "planned"
        ]
        establishment_verbs = ("已经成立", "已成立", "共同建立", "建立了", "已经形成", "形成了")
        negations = ("尚未", "还未", "计划", "准备", "条件", "未来")
        for event in planned:
            label = event.name
            for suffix in ("的成立", "成立事件", "成立"):
                label = label.removesuffix(suffix)
            if len(label) < 2:
                continue
            start = 0
            while True:
                index = detail.find(label, start)
                if index < 0:
                    break
                window = detail[max(0, index - 35): index + len(label) + 50]
                if (
                    any(verb in window for verb in establishment_verbs)
                    and not any(word in window for word in negations)
                ):
                    issues.append(f"把尚未发生的“{event.name}”写成了既成事实")
                    break
                start = index + len(label)
        # Cross-entry real-name / 本名 collisions
        issues.extend(
            NameRegistry.from_store(self.store).real_name_conflicts(entry_id, detail)
        )
        return issues

    def occupied_names_block(self, *, max_chars: int = 3500) -> str:
        """Render occupied-name prompt block from the current planning store."""
        return NameRegistry.from_store(self.store).render_occupied_block(
            max_chars=max_chars,
        )

    def render_brief(
        self,
        entry_ids: list[str] | None = None,
        *,
        volume_number: int | None = None,
        max_entries: int = 16,
        entry_types: list[str] | None = None,
    ) -> str:
        """Render an author-only, token-bounded brief for planning prompts."""
        wanted = set(entry_ids or [])
        allowed_types = set(entry_types or VALID_TYPES)
        entries = [
            entry for entry in self.store.list_entries()
            if entry.type in allowed_types and (not wanted or entry.id in wanted)
        ][:max_entries]
        if not entries:
            return "暂无完整设定集条目。若剧情需要新出场主体，请提出结构化设定与关系提议。"

        selected = {entry.id for entry in entries}
        lines = ["【完整设定集（仅供规划，禁止向读者直接泄露幕后字段）】"]
        for entry in entries:
            type_label = _TYPE_LABELS.get(entry.type, entry.type)
            volume_role = entry.volume_roles.get(str(volume_number), "") if volume_number else ""
            details_bits: list[str] = []
            if entry.narrative_role:
                details_bits.append(f"叙事职责：{entry.narrative_role}")
            if entry.surface_summary:
                details_bits.append(f"公开面：{entry.surface_summary}")
            if entry.secret_truth:
                details_bits.append(f"幕后真相：{entry.secret_truth}")
            if entry.reveal_strategy:
                details_bits.append(f"首次登场：{entry.reveal_strategy}")
            if entry.detail:
                details_bits.append(f"详情摘要：{entry.detail[:500]}")
            for key, value in (entry.details or {}).items():
                if key in {"arc"} or not value:
                    continue
                if isinstance(value, dict):
                    continue
                details_bits.append(f"{key}：{value}")
            if volume_role:
                details_bits.append(f"本卷职责：{volume_role}")
            if entry.revealed_ref:
                details_bits.append(f"已揭示关联：{entry.revealed_ref}")
            lines.append(
                f"- [{type_label}] {entry.id}（{entry.name}）："
                f"{'；'.join(details_bits) or '待定'}"
            )

        for relation in self.store.list_relationships():
            if relation.source_id not in selected or relation.target_id not in selected:
                continue
            tension = relation.conflict or relation.stakes or relation.status
            lines.append(
                f"- 关系 {relation.source_id} → {relation.target_id}"
                f"（{relation.relationship_type}）：{tension or '待定'}"
            )
        return "\n".join(lines)

    def render_full(
        self,
        entry_ids: list[str] | None = None,
        *,
        volume_number: int | None = None,
        max_chars: int | None = 200_000,
    ) -> str:
        """Render full planning-codex entries for framework / outline prompts.

        Unlike :meth:`render_brief`, detail is not truncated per entry. If the
        total exceeds *max_chars*, lower-priority types are dropped first
        (timeline → item → … → character).
        """
        wanted = set(entry_ids or [])
        by_type: dict[str, list] = {t: [] for t in DETAIL_TYPE_ORDER}
        for entry in self.store.list_entries():
            if wanted and entry.id not in wanted:
                continue
            if entry.type in by_type:
                by_type[entry.type].append(entry)

        # Build blocks in DETAIL_TYPE_ORDER; truncate by keep-priority if needed.
        type_blocks: list[tuple[str, str]] = []
        for entry_type in DETAIL_TYPE_ORDER:
            entries = by_type.get(entry_type) or []
            if not entries:
                continue
            label = _TYPE_LABELS.get(entry_type, entry_type)
            parts = [f"## {label}"]
            for entry in entries:
                parts.append(self._format_entry_full(entry, volume_number=volume_number))
            type_blocks.append((entry_type, "\n\n".join(parts)))

        all_selected = {
            e.id
            for entries in by_type.values()
            for e in entries
        }
        if not all_selected:
            return "暂无完整设定集条目。"

        rel_lines: list[str] = []
        for relation in self.store.list_relationships():
            if relation.source_id not in all_selected or relation.target_id not in all_selected:
                continue
            tension = relation.conflict or relation.stakes or relation.status
            rel_lines.append(
                f"- 关系 {relation.source_id} → {relation.target_id}"
                f"（{relation.relationship_type}）：{tension or '待定'}"
            )
        relations_block = ""
        if rel_lines:
            relations_block = "\n\n## 关系\n" + "\n".join(rel_lines)

        header = "【完整设定集全文（仅供规划，禁止向读者直接泄露幕后字段）】\n\n"
        if max_chars is None or max_chars <= 0:
            body = "\n\n".join(block for _, block in type_blocks) + relations_block
            return header + body

        keep_rank = {t: i for i, t in enumerate(_FULL_RENDER_KEEP_PRIORITY)}
        ordered = sorted(type_blocks, key=lambda tb: keep_rank.get(tb[0], 99))
        kept_map: dict[str, str] = {}
        dropped: list[str] = []
        used = len(header) + len(relations_block)
        for entry_type, block in ordered:
            extra = (2 if kept_map else 0) + len(block)
            if kept_map and used + extra > max_chars:
                dropped.append(entry_type)
                continue
            if not kept_map and used + len(block) > max_chars:
                room = max(max_chars - used - 20, 500)
                kept_map[entry_type] = block[:room] + "\n…（该类型条目已截断）"
                used = max_chars
                dropped.append(f"{entry_type}(截断)")
                break
            kept_map[entry_type] = block
            used += extra

        # Restore stable display order.
        kept_blocks = [
            kept_map[t] for t in DETAIL_TYPE_ORDER if t in kept_map
        ]
        body = "\n\n".join(kept_blocks) + relations_block
        if dropped:
            labels = "、".join(
                _TYPE_LABELS.get(t.replace("(截断)", ""), t) if "(截断)" not in t
                else f"{_TYPE_LABELS.get(t.replace('(截断)', ''), t)}(截断)"
                for t in dropped
            )
            body += f"\n\n（因篇幅限制，以下类型未完整纳入：{labels}）"
        return header + body

    def render_entries_full(
        self,
        entry_ids: list[str],
        *,
        volume_number: int | None = None,
        max_chars: int | None = 200_000,
    ) -> str:
        """Full render restricted to the given entry ids."""
        if not entry_ids:
            return "（无涉及实体）"
        return self.render_full(
            entry_ids,
            volume_number=volume_number,
            max_chars=max_chars,
        )

    def _format_entry_full(
        self,
        entry: PlanningCodexEntry,
        *,
        volume_number: int | None = None,
    ) -> str:
        type_label = _TYPE_LABELS.get(entry.type, entry.type)
        lines = [f"### [{type_label}] {entry.id}（{entry.name}）"]
        if entry.aliases:
            lines.append(f"- 别名：{'、'.join(entry.aliases)}")
        if entry.narrative_role:
            lines.append(f"- 叙事职责：{entry.narrative_role}")
        if entry.surface_summary:
            lines.append(f"- 公开面：{entry.surface_summary}")
        if entry.secret_truth:
            lines.append(f"- 幕后真相：{entry.secret_truth}")
        if entry.reveal_strategy:
            lines.append(f"- 首次登场：{entry.reveal_strategy}")
        if volume_number is not None:
            volume_role = entry.volume_roles.get(str(volume_number), "")
            if volume_role:
                lines.append(f"- 本卷职责：{volume_role}")
        if entry.revealed_ref:
            lines.append(f"- 已揭示关联：{entry.revealed_ref}")
        if entry.detail:
            lines.append(f"- 详情：\n{entry.detail}")
        for key, value in (entry.details or {}).items():
            if key in {"arc"} or value in (None, "", {}, []):
                continue
            if isinstance(value, dict):
                lines.append(f"- {key}：{json.dumps(value, ensure_ascii=False)}")
            else:
                lines.append(f"- {key}：{value}")
        if entry.body:
            lines.append(f"- 备注：\n{entry.body}")
        return "\n".join(lines)

    def render_index(self, *, max_per_type: int = 40) -> str:
        """Compact index of all entry ids grouped by type."""
        lines: list[str] = []
        for entry_type in VALID_TYPES:
            items = self.store.list_entries(entry_type)
            total = len(items)
            shown = items[:max_per_type]
            if not shown:
                continue
            label = _TYPE_LABELS.get(entry_type, entry_type)
            joined = "、".join(f"{e.id}({e.name})" for e in shown)
            if total > max_per_type:
                joined += f"…等共{total}条"
            lines.append(f"{label}：" + joined)
        return "\n".join(lines) if lines else "（空）"

    def build_graph(
        self,
        *,
        entry_types: list[str] | None = None,
        focus: str | None = None,
        depth: int = 1,
        include_implicit_world: bool = False,
    ) -> dict[str, list[dict]]:
        """Project codex entries and relations into a UI-ready graph."""
        allowed = set(entry_types or VALID_TYPES)
        entries = [
            entry for entry in self.store.list_entries()
            if entry.type in allowed
        ]
        visible_ids = {entry.id for entry in entries}
        relations = [
            relation for relation in self.store.list_relationships()
            if relation.source_id in visible_ids and relation.target_id in visible_ids
        ]

        implicit_edges: list[dict] = []
        if include_implicit_world:
            worlds = [entry.id for entry in entries if entry.type == "worldbuilding"]
            for world_id in worlds:
                for entry in entries:
                    if entry.id == world_id:
                        continue
                    implicit_edges.append({
                        "id": f"implicit_world_{world_id}_{entry.id}",
                        "source": world_id,
                        "target": entry.id,
                        "relationship_type": "world_context",
                        "kind": "implicit_world",
                        "label": "世界规则",
                    })

        explicit_edges = [
            {
                "id": relation.id,
                "source": relation.source_id,
                "target": relation.target_id,
                "relationship_type": relation.relationship_type,
                "kind": "explicit",
                "label": relation.relationship_type,
                "conflict": relation.conflict,
                "stakes": relation.stakes,
                "status": relation.status,
                "tags": relation.tags,
            }
            for relation in relations
        ]
        all_edges = [*explicit_edges, *implicit_edges]

        if focus and focus in visible_ids:
            adjacency: dict[str, set[str]] = {entry_id: set() for entry_id in visible_ids}
            for edge in all_edges:
                adjacency[edge["source"]].add(edge["target"])
                adjacency[edge["target"]].add(edge["source"])
            focused = {focus}
            frontier = {focus}
            for _ in range(max(depth, 0)):
                next_frontier = {
                    neighbour
                    for node_id in frontier
                    for neighbour in adjacency.get(node_id, set())
                } - focused
                focused.update(next_frontier)
                frontier = next_frontier
            entries = [entry for entry in entries if entry.id in focused]
            all_edges = [
                edge for edge in all_edges
                if edge["source"] in focused and edge["target"] in focused
            ]

        degree: dict[str, int] = {entry.id: 0 for entry in entries}
        for edge in all_edges:
            degree[edge["source"]] = degree.get(edge["source"], 0) + 1
            degree[edge["target"]] = degree.get(edge["target"], 0) + 1
        nodes = [
            {
                "id": entry.id,
                "name": entry.name,
                "type": entry.type,
                "summary": entry.surface_summary,
                "narrative_role": entry.narrative_role,
                "tags": entry.tags,
                "planned": (
                    entry.type == "timeline"
                    and entry.details.get("event_status") == "planned"
                ),
                "expansion_depth": entry.details.get("expansion_depth", 0),
                "expansion_run_id": entry.details.get("expansion_run_id", ""),
                "degree": degree.get(entry.id, 0),
            }
            for entry in entries
        ]
        return {"nodes": nodes, "edges": all_edges}

    def resolve_entry_ids(
        self,
        raw_ids: list[str],
        *,
        codex: "CodexStore | None" = None,
    ) -> tuple[list[str], list[str]]:
        """Resolve ids against planning codex first, then revealed codex via revealed_ref."""
        from ..codex import resolve_entity_ids

        resolved: list[str] = []
        warnings: list[str] = []
        planning_by_id = {e.id: e for e in self.store.list_entries()}
        planning_by_ref = {
            e.revealed_ref: e.id for e in planning_by_id.values() if e.revealed_ref
        }

        for raw in raw_ids:
            rid = str(raw).strip()
            if not rid:
                continue
            if rid.startswith("new:"):
                resolved.append(rid[4:].strip() or rid)
                continue
            if rid in planning_by_id:
                resolved.append(rid)
                continue
            if rid in planning_by_ref:
                canonical = planning_by_ref[rid]
                warnings.append(f"规划 id 对齐：{rid} → {canonical}（revealed_ref）")
                resolved.append(canonical)
                continue
            if codex is not None:
                batch, log = resolve_entity_ids([rid], codex)
                if batch:
                    resolved.append(batch[0])
                    for r in log:
                        if r.raw_id != r.canonical_id:
                            warnings.append(
                                f"已揭示设定 id 对齐：{r.raw_id or rid} → {r.canonical_id}"
                            )
                    continue
            resolved.append(rid)
        return resolved, warnings

    @staticmethod
    def _new_entry(proposal: PlanningCodexProposal, source: str) -> PlanningCodexEntry:
        fields = proposal.model_dump(exclude_none=True)
        fields.pop("id", None)
        entry_type = str(fields.pop("type", None) or "").strip()
        if entry_type not in VALID_TYPES:
            raise ValueError(
                f"新建设定 {proposal.id!r} 缺少有效 type，得到 {entry_type!r}"
            )
        name = str(fields.pop("name", None) or "").strip()
        if not name:
            raise ValueError(f"新建设定 {proposal.id!r} 缺少 name")
        return PlanningCodexEntry(
            id=proposal.id,
            name=name,
            type=entry_type,
            source=source,
            **fields,
        )

    @staticmethod
    def _new_relationship(
        proposal: RelationshipProposal, source: str
    ) -> PlanningRelationship | None:
        source_id = proposal.resolved_source_id()
        target_id = proposal.resolved_target_id()
        if not source_id or not target_id:
            return None
        fields = proposal.model_dump(exclude_none=True)
        fields.pop("id", None)
        fields.pop("source_entity_id", None)
        fields.pop("target_entity_id", None)
        return PlanningRelationship(
            id=proposal.id,
            source_id=source_id,
            target_id=target_id,
            source=source,
            **{k: v for k, v in fields.items() if k not in {"source_id", "target_id"}},
        )

    @staticmethod
    def _relationship_endpoints_exist(
        relationship: PlanningRelationship,
        entries: dict[str, PlanningCodexEntry],
    ) -> bool:
        return (
            relationship.source_id in entries
            and relationship.target_id in entries
        )

    @staticmethod
    def _merge_entry(
        entry: PlanningCodexEntry,
        proposal: PlanningCodexProposal,
        result: ReconcileResult,
    ) -> bool:
        from .models import _LOCK_TO_ENTRY

        changed = False
        for field_name, value in proposal.model_dump(exclude_none=True).items():
            if field_name == "id":
                continue
            lock_aliases = {field_name, _LOCK_TO_ENTRY.get(field_name, field_name)}
            locked_name = next((name for name in lock_aliases if entry.is_locked(name)), None)
            if locked_name is not None:
                # Prefer legacy label when the lock was set via character field names.
                from .models import _LOCK_TO_ENTITY
                label = _LOCK_TO_ENTITY.get(locked_name, locked_name)
                result.skipped_locked_fields.append(f"entity:{entry.id}.{label}")
                continue
            if field_name == "volume_roles":
                value = {**entry.volume_roles, **value}
            elif field_name == "details":
                # Merge details but respect locks on nested detail keys via
                # legacy character field names stored in field_locks.
                merged = {**entry.details}
                for dk, dv in value.items():
                    mapped = _LOCK_TO_ENTRY.get(dk, dk)
                    if entry.is_locked(dk) or entry.is_locked(mapped):
                        result.skipped_locked_fields.append(f"entity:{entry.id}.{dk}")
                        continue
                    merged[dk] = dv
                value = merged
            if getattr(entry, field_name) != value:
                setattr(entry, field_name, value)
                changed = True
        return changed

    @staticmethod
    def _merge_relationship(
        relationship: PlanningRelationship,
        proposal: RelationshipProposal,
        result: ReconcileResult,
    ) -> bool:
        changed = False
        for field_name, value in proposal.model_dump(exclude_none=True).items():
            if field_name in {"id", "source_entity_id", "target_entity_id"}:
                continue
            if field_name == "source_id":
                field_name = "source_id"
            if relationship.is_locked(field_name):
                result.skipped_locked_fields.append(
                    f"relationship:{relationship.id}.{field_name}"
                )
                continue
            if getattr(relationship, field_name, None) != value:
                setattr(relationship, field_name, value)
                changed = True
        src = proposal.resolved_source_id()
        tgt = proposal.resolved_target_id()
        if src and relationship.source_id != src:
            if not relationship.is_locked("source_id"):
                relationship.source_id = src
                changed = True
        if tgt and relationship.target_id != tgt:
            if not relationship.is_locked("target_id"):
                relationship.target_id = tgt
                changed = True
        return changed


EntityNetworkService = PlanningCodexService
