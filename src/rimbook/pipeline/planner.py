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
    FrameworkCastEntry, FrameworkCraftFocus, FrameworkReaderLens,
    FrameworkStage, VolumeFramework,
)
from ..planning_entities import (
    DETAIL_TYPE_ORDER,
    ExpansionBudget,
    ExpansionCandidate,
    PlanningCodexChanges,
    PlanningCodexService,
    WorldExpander,
    incomplete_entry_fields,
    merge_entry_labels,
    partition_raw_entries,
    render_incomplete_entries,
)

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
        *,
        planning_entities: PlanningCodexService | None = None,
        threads: ThreadStore | None = None,
        trace: TraceStore | None = None,
        project_name: str = "",
        expansion_hard_max_calls: int = 80,
        expansion_hard_max_entries: int = 120,
        expansion_hard_max_relationships: int = 360,
    ) -> None:
        self.llm = llm
        self.prompts = prompts
        self.outline = outline
        self.codex = codex
        self.planning_entities = planning_entities
        self.threads = threads
        self.trace = trace if trace is not None else NULL_TRACE
        self.project_name = project_name
        self.expansion_hard_max_calls = expansion_hard_max_calls
        self.expansion_hard_max_entries = expansion_hard_max_entries
        self.expansion_hard_max_relationships = expansion_hard_max_relationships

    # ------------------------------------------------------------------
    # Synopsis
    # ------------------------------------------------------------------
    def plan_synopsis(self, premise: str, *, persist: bool = True) -> str:
        """Generate the macro whole-novel synopsis from a short premise."""
        messages = self.llm.as_chat(
            system=self.prompts.foundation_synopsis_system or self.prompts.synopsis_system,
            user=(self.prompts.foundation_synopsis_user or self.prompts.synopsis_user).format(
                premise=premise
            ),
        )
        with self.trace.begin("synopsis", project=self.project_name) as t:
            result = self.llm.generate(messages, temperature=0.8)
            t.record(messages, result)
        text = result.content.strip()
        if persist:
            self.outline.write_synopsis(text)
        return text

    def plan_foundation(
        self,
        premise: str,
        *,
        persist: bool = True,
        expansion_coefficient: int = 1,
    ) -> Generator[dict, None, None]:
        """Project foundation: macro synopsis, rough codex, then layered details."""
        yield {"event": "step", "data": {
            "step": 1, "status": "running",
            "message": "正在生成宏观全书梗概…",
        }}
        synopsis = self.plan_synopsis(premise, persist=persist)
        yield {"event": "step", "data": {
            "step": 1, "status": "done",
            "message": "宏观梗概已生成",
            "synopsis_length": len(synopsis),
        }}

        cast_result: dict[str, object] = {}
        if self.planning_entities is not None:
            yield {"event": "step", "data": {
                "step": 2, "status": "running",
                "message": "正在初始化完整设定集…",
            }}
            existing_index = self.planning_entities.render_index()
            messages = self.llm.as_chat(
                system=self.prompts.foundation_codex_system,
                user=self.prompts.foundation_codex_user.format(
                    premise=premise,
                    synopsis=synopsis,
                    existing_index=existing_index,
                    occupied_names=self.planning_entities.occupied_names_block(),
                ),
            )
            with self.trace.begin("foundation_codex", project=self.project_name) as t:
                data: dict = {}
                last_error: ValueError | None = None
                for attempt in range(1, 3):
                    try:
                        data = self.llm.generate_json(
                            messages,
                            temperature=0.45 if attempt == 1 else 0.3,
                            max_tokens=12000,
                        )
                        t.record(messages, data, model=self.llm.default_model)
                        last_error = None
                        break
                    except ValueError as exc:
                        last_error = exc
                        t.record(
                            messages,
                            None,
                            model=self.llm.default_model,
                            warnings=[f"第 {attempt} 次 JSON 解析失败: {exc}"],
                        )
                if last_error is not None:
                    raise last_error
            raw_entries = data.get("entries") if isinstance(data, dict) else []
            if not isinstance(raw_entries, list):
                raw_entries = []
            ready_entries, label_warnings = self._relabel_incomplete_entries(
                raw_entries,
                synopsis=synopsis,
                require_existence=True,
                stage="foundation_relabel",
            )
            if label_warnings:
                yield {"event": "progress", "data": {
                    "step": 2,
                    "phase": "foundation_relabel",
                    "message": "；".join(label_warnings[:6]),
                    "warnings": label_warnings,
                }}
            reconcile = self.planning_entities.apply_foundation_entries(
                ready_entries, source="foundation", require_existence=True,
            )
            reconcile.warnings[:0] = label_warnings
            rel_changes = PlanningCodexChanges.from_payload(data)
            if rel_changes.relationships:
                rel_result = self.planning_entities.reconcile(
                    PlanningCodexChanges(relationships=rel_changes.relationships),
                    source="foundation",
                )
                reconcile.created_relationships.extend(rel_result.created_relationships)
                reconcile.updated_relationships.extend(rel_result.updated_relationships)
                reconcile.skipped_relationships.extend(rel_result.skipped_relationships)
            cast_result = reconcile.model_dump()
            yield {"event": "step", "data": {
                "step": 2, "status": "done",
                "message": (
                    f"完整设定集已初始化（{reconcile.change_count} 项变更，"
                    f"{len(reconcile.warnings)} 条警告）"
                ),
                "changes": cast_result,
                "entry_count": len(self.planning_entities.store.list_entries()),
                "relationship_count": len(self.planning_entities.store.list_relationships()),
            }}
            yield from self.generate_codex_details(
                synopsis=synopsis,
                only_missing=True,
                step_offset=3,
            )
            if expansion_coefficient > 1:
                yield from self.expand_world(
                    coefficient=expansion_coefficient,
                    synopsis=synopsis,
                    step_offset=9,
                )
        else:
            yield {"event": "step", "data": {
                "step": 2, "status": "done",
                "message": "未启用完整设定集服务，跳过设定初始化",
            }}

    def _relabel_incomplete_entries(
        self,
        raw_entries: list,
        *,
        synopsis: str,
        require_existence: bool = True,
        stage: str = "foundation_relabel",
    ) -> tuple[list[dict], list[str]]:
        """Batch-ask the model to fill missing required fields; never invent type=character."""
        warnings: list[str] = []
        complete, incomplete = partition_raw_entries(
            raw_entries,
            require_existence=require_existence,
        )
        if not incomplete:
            return complete, warnings

        warnings.append(
            f"检测到 {len(incomplete)} 条设定缺少必填字段，正在一次性补全…"
        )
        messages = self.llm.as_chat(
            system=self.prompts.foundation_relabel_system,
            user=self.prompts.foundation_relabel_user.format(
                synopsis=synopsis or "",
                incomplete_entries=render_incomplete_entries(incomplete),
            ),
        )
        patches_by_id: dict[str, dict] = {}
        with self.trace.begin(stage, project=self.project_name) as trace:
            try:
                labeled = self.llm.generate_json(
                    messages,
                    temperature=0.2,
                    max_tokens=8000,
                )
                trace.record(messages, labeled, model=self.llm.default_model)
            except ValueError as exc:
                trace.record(
                    messages,
                    None,
                    model=self.llm.default_model,
                    warnings=[f"必填字段补全 JSON 解析失败: {exc}"],
                )
                warnings.append(f"必填字段补全失败，将跳过不完整条目: {exc}")
                labeled = {}
        for item in (labeled.get("entries") if isinstance(labeled, dict) else None) or []:
            if not isinstance(item, dict):
                continue
            entry_id = str(item.get("id") or "").strip()
            if entry_id:
                patches_by_id[entry_id] = item

        repaired: list[dict] = []
        for item in incomplete:
            entry_id = str(item.get("id") or "").strip() or "?"
            merged = merge_entry_labels(item, patches_by_id.get(entry_id) or {})
            still_missing = incomplete_entry_fields(
                merged, require_existence=require_existence,
            )
            if still_missing:
                warnings.append(
                    f"跳过 {entry_id}：补全后仍缺 {', '.join(still_missing)}"
                )
                continue
            repaired.append(merged)

        warnings.append(
            f"必填字段补全完成：成功 {len(repaired)}/{len(incomplete)}"
        )
        return complete + repaired, warnings

    def generate_codex_details(
        self,
        *,
        synopsis: str | None = None,
        entry_ids: list[str] | None = None,
        only_missing: bool = True,
        step_offset: int = 1,
    ) -> Generator[dict, None, None]:
        """Generate long-form details in macro-to-micro type order.

        Each entry is persisted immediately. A malformed or low-quality result
        is isolated as a warning so later entries can still complete.
        """
        if self.planning_entities is None:
            return
        synopsis_text = synopsis
        if synopsis_text is None:
            synopsis_text = self.outline.read_synopsis().strip()
        wanted = set(entry_ids or [])

        for index, entry_type in enumerate(DETAIL_TYPE_ORDER):
            step = step_offset + index
            entries = self.planning_entities.store.list_entries(entry_type)
            if wanted:
                entries = [entry for entry in entries if entry.id in wanted]
            if only_missing:
                entries = [entry for entry in entries if not entry.detail.strip()]

            yield {"event": "step", "data": {
                "step": step,
                "status": "running",
                "phase": "codex_detail",
                "entry_type": entry_type,
                "total": len(entries),
                "message": f"正在细化{_planning_type_label(entry_type)}详情…",
            }}

            completed = 0
            warnings: list[str] = []
            for position, entry in enumerate(entries, start=1):
                yield {"event": "progress", "data": {
                    "step": step,
                    "entry_type": entry_type,
                    "entry_id": entry.id,
                    "current": position,
                    "total": len(entries),
                    "message": (
                        f"正在细化{_planning_type_label(entry_type)}"
                        f"「{entry.name}」（{position}/{len(entries)}）…"
                    ),
                }}
                try:
                    self.generate_entry_detail(entry.id, synopsis=synopsis_text)
                    completed += 1
                except (ValueError, FileNotFoundError) as exc:
                    warnings.append(f"{entry.id}: {exc}")

            yield {"event": "step", "data": {
                "step": step,
                "status": "done",
                "phase": "codex_detail",
                "entry_type": entry_type,
                "completed": completed,
                "skipped": len(entries) - completed,
                "warnings": warnings,
                "message": (
                    f"{_planning_type_label(entry_type)}详情完成"
                    f"（{completed}/{len(entries)}）"
                ),
            }}

    def generate_entry_detail(
        self,
        entry_id: str,
        *,
        synopsis: str | None = None,
    ) -> dict[str, object]:
        """Generate and persist one entry's long-form detail."""
        if self.planning_entities is None:
            raise RuntimeError("未启用完整设定集服务")
        entry = self.planning_entities.store.get_entry(entry_id)
        synopsis_text = synopsis
        if synopsis_text is None:
            synopsis_text = self.outline.read_synopsis().strip()
        context = self.planning_entities.render_detail_context(
            entry_id,
            synopsis=synopsis_text,
        )
        system_prompt = getattr(
            self.prompts,
            f"codex_detail_{entry.type}_system",
        )
        correction = ""
        data: dict = {}
        detail = ""
        details_patch: dict = {}
        issues: list[str] = []
        for attempt in range(1, 3):
            user_prompt = self.prompts.codex_detail_user.format(context=context)
            if correction:
                user_prompt += (
                    "\n\n【上次输出未通过质量门禁，必须修正】\n"
                    + correction
                    + "\n请重新输出完整 JSON。"
                )
            messages = self.llm.as_chat(
                system=system_prompt,
                user=user_prompt,
            )
            with self.trace.begin(
                "planning_codex_detail",
                project=self.project_name,
                entry_id=entry_id,
                entry_type=entry.type,
                attempt=attempt,
            ) as trace:
                data = self.llm.generate_json(
                    messages,
                    temperature=0.5,
                    max_tokens=6000,
                )
                trace.record(messages, data, model=self.llm.default_model)

            detail = str(data.get("detail") or "").strip()
            raw_patch = data.get("details_patch") or {}
            if not isinstance(raw_patch, dict):
                issues = ["details_patch 必须是对象"]
                details_patch = {}
            else:
                details_patch = raw_patch
                issues = self.planning_entities.detail_quality_issues(
                    entry_id,
                    detail,
                )
            if not issues:
                break
            correction = "\n".join(f"- {issue}" for issue in issues)
        if issues:
            raise ValueError("；".join(issues) + "，重试后仍未通过，未写入")

        result = self.planning_entities.apply_detail(
            entry_id,
            detail=detail,
            details_patch=details_patch,
        )
        return {
            "entry_id": entry_id,
            "entry_type": entry.type,
            "detail_length": len(detail),
            "details_keys": sorted(details_patch),
            "changes": result.model_dump(),
        }

    def expand_world(
        self,
        *,
        coefficient: int,
        synopsis: str | None = None,
        seed_ids: list[str] | None = None,
        step_offset: int = 1,
    ) -> Generator[dict, None, None]:
        """Expand completed details into a budgeted, relational world graph."""
        if self.planning_entities is None:
            return
        budget = ExpansionBudget.for_coefficient(coefficient)
        if budget.max_depth == 0:
            return
        budget.max_llm_calls = min(
            budget.max_llm_calls,
            self.expansion_hard_max_calls,
        )
        synopsis_text = synopsis
        if synopsis_text is None:
            synopsis_text = self.outline.read_synopsis().strip()
        initial_seeds = [
            entry.id
            for entry in self.planning_entities.store.list_entries()
            if entry.detail.strip()
        ]
        if seed_ids:
            wanted = set(seed_ids)
            initial_seeds = [entry_id for entry_id in initial_seeds if entry_id in wanted]
        expander = WorldExpander(self.planning_entities)
        state = expander.start_or_resume(
            coefficient=coefficient,
            seed_ids=initial_seeds,
        )
        current_seeds = list(state.seed_ids)

        for depth in range(state.current_depth, budget.max_depth + 1):
            step = step_offset + depth - 1
            seeds = [
                entry_id
                for entry_id in current_seeds
                if entry_id not in set(state.processed_seed_ids)
            ]
            if not seeds:
                state.complete = True
                state.stopped_reason = "没有未处理的扩展种子"
                expander.save_state(state)
                break
            yield {"event": "step", "data": {
                "step": step,
                "status": "running",
                "phase": "world_expand",
                "depth": depth,
                "max_depth": budget.max_depth,
                "coefficient": coefficient,
                "seed_count": len(seeds),
                "created": len(state.created_entry_ids),
                "remaining_budget": max(
                    budget.max_new_per_run - len(state.created_entry_ids),
                    0,
                ),
                "message": (
                    f"正在扩展真实世界（第 {depth}/{budget.max_depth} 层，"
                    f"{len(seeds)} 个种子）…"
                ),
            }}

            mined: list[ExpansionCandidate] = []
            warnings: list[str] = []
            for batch_start in range(0, len(seeds), 6):
                if state.llm_calls_used >= budget.max_llm_calls:
                    warnings.append("达到 LLM 调用硬上限")
                    break
                batch_ids = seeds[batch_start: batch_start + 6]
                yield {"event": "progress", "data": {
                    "phase": "world_expand",
                    "depth": depth,
                    "message": (
                        f"正在从第 {batch_start + 1}–"
                        f"{min(batch_start + len(batch_ids), len(seeds))} 个种子挖掘关键存在…"
                    ),
                }}
                seed_context = self._format_expansion_seed_context(batch_ids)
                messages = self.llm.as_chat(
                    system=self.prompts.world_expand_system,
                    user=self.prompts.world_expand_user.format(
                        synopsis=synopsis_text,
                        existing_index=self.planning_entities.render_index(
                            max_per_type=80
                        ),
                        occupied_names=self.planning_entities.occupied_names_block(),
                        seed_context=seed_context,
                        coefficient=coefficient,
                        depth=depth,
                        max_depth=budget.max_depth,
                        max_candidates_per_seed=budget.max_candidates_per_seed,
                        remaining_budget=max(
                            budget.max_new_per_run - len(state.created_entry_ids),
                            0,
                        ),
                    ),
                )
                with self.trace.begin(
                    "world_expand_mine",
                    project=self.project_name,
                    depth=depth,
                    seed_ids=batch_ids,
                    run_id=state.run_id,
                ) as trace:
                    try:
                        data = self.llm.generate_json(
                            messages,
                            temperature=0.45,
                            max_tokens=12000,
                        )
                        trace.record(messages, data, model=self.llm.default_model)
                    except ValueError as exc:
                        trace.record(
                            messages,
                            None,
                            model=self.llm.default_model,
                            warnings=[str(exc)],
                        )
                        warnings.append(f"候选挖掘失败: {exc}")
                        state.llm_calls_used += 1
                        expander.save_state(state)
                        continue
                state.llm_calls_used += 1
                expander.save_state(state)
                for raw_candidate in data.get("candidates") or []:
                    if not isinstance(raw_candidate, dict):
                        continue
                    try:
                        candidate = ExpansionCandidate.model_validate(raw_candidate)
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"跳过无效候选: {exc}")
                        continue
                    candidate.source_entry_ids = [
                        entry_id
                        for entry_id in candidate.source_entry_ids
                        if entry_id in batch_ids
                    ]
                    if not candidate.source_entry_ids:
                        warnings.append(f"候选 {candidate.name} 缺少有效来源")
                        continue
                    mined.append(candidate)

            deduped, dedup_warnings = expander.deduplicate(mined)
            warnings.extend(dedup_warnings)
            selected = expander.select(deduped, budget=budget, state=state)
            if (
                len(self.planning_entities.store.list_entries())
                >= self.expansion_hard_max_entries
            ):
                selected = [
                    candidate for candidate in selected if candidate.existing_match_id
                ]
                warnings.append("达到完整设定集条目硬上限")
            if (
                len(self.planning_entities.store.list_relationships())
                >= self.expansion_hard_max_relationships
            ):
                selected = []
                warnings.append("达到关系数量硬上限")

            created_ids, materialize_result = expander.materialize(
                selected,
                depth=depth,
                state=state,
            )
            warnings.extend(materialize_result.warnings)
            completed_details: list[str] = []
            for entry_type in DETAIL_TYPE_ORDER:
                type_ids = [
                    entry_id
                    for entry_id in created_ids
                    if self.planning_entities.store.get_entry(entry_id).type == entry_type
                ]
                for position, entry_id in enumerate(type_ids, start=1):
                    if state.llm_calls_used >= budget.max_llm_calls:
                        warnings.append("详情生成前达到 LLM 调用硬上限")
                        break
                    entry = self.planning_entities.store.get_entry(entry_id)
                    yield {"event": "progress", "data": {
                        "phase": "world_expand_detail",
                        "depth": depth,
                        "entry_id": entry_id,
                        "entry_type": entry_type,
                        "message": (
                            f"正在细化扩展条目「{entry.name}」"
                            f"（{position}/{len(type_ids)}）…"
                        ),
                    }}
                    try:
                        self.generate_entry_detail(entry_id, synopsis=synopsis_text)
                        completed_details.append(entry_id)
                    except ValueError as exc:
                        warnings.append(f"{entry_id} 详情失败: {exc}")
                    state.llm_calls_used += 1
                    expander.save_state(state)

            state.processed_seed_ids.extend(
                entry_id
                for entry_id in seeds
                if entry_id not in state.processed_seed_ids
            )
            state.current_depth = depth + 1
            current_seeds = completed_details
            state.seed_ids = list(current_seeds)
            if not created_ids:
                state.complete = True
                state.stopped_reason = "本层没有值得物化的新条目"
            elif depth >= budget.max_depth:
                state.complete = True
                state.stopped_reason = "达到最大扩展深度"
            elif len(state.created_entry_ids) >= budget.max_new_per_run:
                state.complete = True
                state.stopped_reason = "达到新条目预算"
            elif state.llm_calls_used >= budget.max_llm_calls:
                state.complete = True
                state.stopped_reason = "达到 LLM 调用预算"
            expander.save_state(state)

            yield {"event": "step", "data": {
                "step": step,
                "status": "done",
                "phase": "world_expand",
                "depth": depth,
                "mined": len(mined),
                "accepted": len(selected),
                "created_entry_ids": created_ids,
                "completed_detail_ids": completed_details,
                "deduplicated": len(mined) - len(deduped),
                "remaining_budget": max(
                    budget.max_new_per_run - len(state.created_entry_ids),
                    0,
                ),
                "llm_calls_used": state.llm_calls_used,
                "warnings": warnings,
                "message": (
                    f"世界扩展第 {depth} 层完成："
                    f"挖掘 {len(mined)}，新建 {len(created_ids)}"
                ),
            }}
            if state.complete:
                break

    def _format_expansion_seed_context(self, seed_ids: list[str]) -> str:
        if self.planning_entities is None:
            return "（无）"
        blocks: list[str] = []
        relations = self.planning_entities.store.list_relationships()
        for seed_id in seed_ids:
            entry = self.planning_entities.store.get_entry(seed_id)
            relation_lines = [
                f"{relation.source_id}->{relation.target_id}"
                f"({relation.relationship_type})"
                for relation in relations
                if relation.source_id == seed_id or relation.target_id == seed_id
            ][:12]
            blocks.append(
                f"### [{entry.type}] {entry.id} · {entry.name}\n"
                f"叙事职责：{entry.narrative_role or '待定'}\n"
                f"现有关系：{'；'.join(relation_lines) or '无'}\n"
                f"详情：\n{entry.detail[:5000]}"
            )
        return "\n\n".join(blocks)

    # ------------------------------------------------------------------
    # Volumes: beat chain → refine → assemble
    # ------------------------------------------------------------------
    def plan_volume_v2(
        self, number: int, *, title: str = ""
    ) -> Generator[dict, None, None]:
        """Five-step volume planning pipeline (yields SSE event dicts).

        Step 1: Writing framework + detailed cast/stage briefing.
        Step 2: Detailed volume outline (title/arc/ending/chapter_count).
        Step 3: Volume cast / planning codex expansion.
        Step 4: Continuous beat chain.
        Step 5: Refine beats + assemble into chapters.
        """
        if self.outline.read_volume(number) is not None:
            raise FileExistsError(f"第 {number} 卷已存在，禁止重复规划")

        synopsis = self.outline.read_synopsis().strip()
        existing = self.outline.list_volumes()
        existing_desc = _format_existing_volumes(existing)
        prev = self.outline.list_chapters()
        prev_recap = _format_prev_chapters(prev[-8:]) if prev else ""
        max_chapter = max((c.number for c in prev), default=0)
        open_threads = self._format_open_threads(max_chapter + 1)
        open_threads_block = (
            f"未回收的情节线索（本卷应推进或回收，不得遗忘）：\n{open_threads}\n\n"
            if open_threads else ""
        )
        prev_recap_block = (
            f"前卷已写章节回顾（请与本卷衔接，避免重复或断层）：\n{prev_recap}\n\n"
            if prev_recap
            else "前卷已写章节回顾：\n（尚无章节——本书可能刚刚开始，请按空白读者期待处理）\n\n"
        )
        revealed_index = self._format_revealed_codex_index()
        title_hint = f"（标题：{title}）" if title else ""
        warnings: list[str] = []

        # === Step 1: Writing framework + detailed cast/stage ===
        yield {"event": "step", "data": {
            "step": 1, "status": "running",
            "message": "正在生成写作框架与详述出场…",
        }}

        planning_full = ""
        if self.planning_entities is not None:
            planning_full = self.planning_entities.render_full(volume_number=number)
        planning_full_block = (
            f"{planning_full}\n\n" if planning_full else "完整设定集全文：\n（暂无）\n\n"
        )

        framework_user = self.prompts.volume_framework_user.format(
            synopsis=synopsis or "（无）",
            existing_desc=existing_desc or "（无）",
            prev_recap_block=prev_recap_block,
            open_threads_block=open_threads_block,
            revealed_index=revealed_index,
            planning_full_block=planning_full_block,
            number=number,
            title_hint=title_hint,
        )
        framework_messages = self.llm.as_chat(
            system=self.prompts.volume_framework_system,
            user=framework_user,
        )
        with self.trace.begin("volume_framework", project=self.project_name, volume=number) as t:
            framework_raw = self.llm.generate_json(framework_messages, temperature=1.0)
            t.record(framework_messages, framework_raw, model=self.llm.default_model)

        known_ids: set[str] = set()
        if self.planning_entities is not None:
            known_ids = {e.id for e in self.planning_entities.store.list_entries()}
        framework, fw_warnings = _parse_volume_framework(
            framework_raw if isinstance(framework_raw, dict) else {},
            volume_number=number,
            known_ids=known_ids,
        )
        warnings.extend(fw_warnings)
        self.outline.save_volume_framework(framework)
        framework_block = _format_framework_block(framework)

        yield {"event": "step", "data": {
            "step": 1, "status": "done",
            "message": (
                f"写作框架已生成（出场 {len(framework.cast)}，"
                f"舞台 {len(framework.stages)}）"
            ),
            "framework": {
                "casting_note": framework.casting_note,
                "cast": [
                    {"id": c.id, "billing": c.billing}
                    for c in framework.cast
                ],
                "stages": [{"id": s.id} for s in framework.stages],
                "involved_ids": list(framework.involved_ids),
            },
            "warnings": list(fw_warnings),
        }}

        # === Step 2: Detailed volume outline ===
        yield {"event": "step", "data": {
            "step": 2, "status": "running",
            "message": "正在生成详尽卷大纲…",
        }}

        involved_full = ""
        if self.planning_entities is not None and framework.involved_ids:
            involved_full = self.planning_entities.render_entries_full(
                framework.involved_ids, volume_number=number,
            )
        elif self.planning_entities is not None:
            involved_full = self.planning_entities.render_full(volume_number=number)
        involved_entities_full = (
            f"本卷涉及实体全量设定：\n{involved_full}\n\n"
            if involved_full else ""
        )

        outline_user = self.prompts.volume_user.format(
            synopsis=synopsis or "（无）",
            existing_desc=existing_desc or "（无）",
            prev_recap_block=prev_recap_block,
            framework_block=framework_block,
            involved_entities_full=involved_entities_full,
            open_threads_block=open_threads_block,
            number=number,
            title_hint=title_hint,
        )
        outline_messages = self.llm.as_chat(
            system=self.prompts.volume_system,
            user=outline_user,
        )
        with self.trace.begin("volume_v2", project=self.project_name, volume=number) as t:
            vol_data = self.llm.generate_json(outline_messages, temperature=1.0)
            t.record(outline_messages, vol_data, model=self.llm.default_model)

        vol_title, arc, ending, chapter_count, vol_warnings = _parse_volume_json(
            vol_data, number=number, title_hint=title
        )
        warnings.extend(vol_warnings)

        vol = VolumeOutline(
            number=number, title=vol_title, arc=arc, ending=ending, chapters=[], recap="",
        )
        self.outline.write_volume(vol)

        yield {"event": "step", "data": {
            "step": 2, "status": "done",
            "message": "详尽卷大纲已生成",
            "volume": {
                "number": number,
                "title": vol_title,
                "arc": arc,
                "ending": ending,
                "chapter_count": chapter_count,
            },
        }}

        # Entity context for later steps: prefer involved full pack.
        if self.planning_entities is not None and framework.involved_ids:
            entity_registry = self._format_entity_registry(
                entry_ids=framework.involved_ids, volume=number, full=True,
            )
        else:
            entity_registry = self._format_entity_registry()
        entity_registry_block = f"{entity_registry}\n\n" if entity_registry else ""

        # === Step 3: Volume cast / planning codex expansion ===
        cast_changes: dict[str, object] = {}
        if self.planning_entities is not None:
            yield {"event": "step", "data": {
                "step": 3, "status": "running",
                "message": "正在扩充本卷出场设定…",
            }}
            story_context = (
                f"全书梗概：\n{synopsis}\n\n"
                f"既有卷：\n{existing_desc or '（无）'}\n\n"
                f"近八章剧情：\n{prev_recap or '（尚无章节）'}"
            )
            if framework.involved_ids:
                planning_brief = self.planning_entities.render_entries_full(
                    framework.involved_ids, volume_number=number,
                )
            else:
                planning_brief = self._format_planning_entity_brief(volume=number)
            cast_messages = self.llm.as_chat(
                system=self.prompts.volume_cast_system,
                user=self.prompts.volume_cast_user.format(
                    volume_title=vol_title,
                    volume_arc=arc,
                    volume_ending=ending,
                    framework_block=framework_block,
                    story_context=story_context,
                    planning_brief=planning_brief,
                    revealed_index=revealed_index,
                    occupied_names=self.planning_entities.occupied_names_block(),
                ),
            )
            with self.trace.begin("volume_cast", project=self.project_name, volume=number) as t:
                cast_data = self.llm.generate_json(cast_messages, temperature=1.0)
                t.record(cast_messages, cast_data, model=self.llm.default_model)
            raw_entries = cast_data.get("entries") if isinstance(cast_data, dict) else []
            if not isinstance(raw_entries, list):
                raw_entries = []
            ready_entries, label_warnings = self._relabel_incomplete_entries(
                raw_entries,
                synopsis=synopsis,
                require_existence=True,
                stage="volume_cast_relabel",
            )
            cast_result = self.planning_entities.apply_foundation_entries(
                ready_entries, source="volume_cast", require_existence=True,
            )
            cast_result.warnings[:0] = label_warnings
            rel_changes = PlanningCodexChanges.from_payload(cast_data)
            if rel_changes.relationships:
                rel_result = self.planning_entities.reconcile(
                    PlanningCodexChanges(relationships=rel_changes.relationships),
                    source="volume_cast",
                )
                cast_result.created_relationships.extend(rel_result.created_relationships)
                cast_result.updated_relationships.extend(rel_result.updated_relationships)
            cast_changes = cast_result.model_dump()
            # Refresh registry after expansion (still prefer involved + new).
            refresh_ids = list(dict.fromkeys([
                *framework.involved_ids,
                *cast_result.created_entries,
                *cast_result.updated_entries,
            ]))
            entity_registry = self._format_entity_registry(
                entry_ids=refresh_ids or None, volume=number, full=True,
            )
            entity_registry_block = f"{entity_registry}\n\n" if entity_registry else ""
            yield {"event": "step", "data": {
                "step": 3, "status": "done",
                "message": f"本卷设定扩充完成（{cast_result.change_count} 项变更）",
                "changes": cast_changes,
            }}
        else:
            yield {"event": "step", "data": {
                "step": 3, "status": "done",
                "message": "未启用完整设定集，跳过本卷设定扩充",
            }}

        # === Step 4: Continuous beat chain ===
        min_beats = max(chapter_count * 3, 12)
        max_beats = chapter_count * 6
        yield {"event": "step", "data": {
            "step": 4, "status": "running",
            "message": f"正在生成连续 beat 链（{min_beats}~{max_beats} 个）…",
        }}

        history = [
            {"role": "user", "content": outline_user},
            {"role": "assistant", "content": json.dumps(dict(vol_data), ensure_ascii=False)},
        ]
        messages2 = self.llm.as_chat(
            system=self.prompts.volume_beats_system.format(
                min_beats=min_beats, max_beats=max_beats,
            ),
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
            beats_data = self.llm.generate_json(messages2, temperature=1.0)
            t.record(messages2, beats_data, model=self.llm.default_model)

        raw_beats, beat_warnings = _parse_raw_beats(
            beats_data,
            planning=self.planning_entities,
            codex=self.codex,
        )
        warnings.extend(beat_warnings)
        if len(raw_beats) < min_beats:
            warnings.append(f"beat 数量 {len(raw_beats)} 低于建议下限 {min_beats}")
        self._apply_planning_entity_changes(beats_data, source="volume_beats")

        beat_data = VolumeBeatData(volume=number, step=4, raw_beats=raw_beats)
        self.outline.save_volume_beats(beat_data)

        yield {"event": "step", "data": {
            "step": 4, "status": "done",
            "message": f"已生成 {len(raw_beats)} 个 beat",
            "beats": [b.model_dump() for b in raw_beats],
        }}

        # === Step 5: Refine + Assemble ===
        yield from self._step4_refine_and_assemble(
            number=number,
            vol_title=vol_title,
            arc=arc,
            ending=ending,
            chapter_count=chapter_count,
            raw_beats=raw_beats,
            start_chapter_number=max_chapter + 1,
            pipeline_step=5,
            involved_ids=framework.involved_ids or None,
        )

    def assemble_from_beats(
        self, volume_number: int, beats: list[RawBeat] | None = None
    ) -> Generator[dict, None, None]:
        """Re-run Step 5 (refine + assemble) using current or provided beats.

        If *beats* is None, loads raw_beats from the persisted beats file.
        Yields SSE event dicts for the assemble step only.
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

        framework = self.outline.load_volume_framework(volume_number)
        involved = framework.involved_ids if framework else None

        yield from self._step4_refine_and_assemble(
            number=volume_number,
            vol_title=vol.title,
            arc=vol.arc,
            ending=vol.ending,
            chapter_count=chapter_count,
            raw_beats=beats,
            start_chapter_number=start_number,
            pipeline_step=5,
            involved_ids=involved or None,
        )

    def _step4_refine_and_assemble(
        self,
        *,
        number: int,
        vol_title: str,
        arc: str,
        ending: str,
        chapter_count: int,
        raw_beats: list[RawBeat],
        start_chapter_number: int,
        pipeline_step: int = 5,
        involved_ids: list[str] | None = None,
    ) -> Generator[dict, None, None]:
        """Group + keynote + per-chapter MicroScenes; persist as final pipeline step."""
        yield {"event": "step", "data": {
            "step": pipeline_step, "status": "running", "phase": "grouping",
            "message": f"正在将 {len(raw_beats)} 个 beat 分组为 {chapter_count} 章并写章基调…",
        }}

        beats_json = json.dumps(
            [b.model_dump() for b in raw_beats], ensure_ascii=False, indent=1,
        )
        if self.planning_entities is not None:
            if involved_ids:
                entity_brief = self.planning_entities.render_entries_full(
                    involved_ids, volume_number=number,
                )
            else:
                entity_brief = self._format_planning_entity_brief(volume=number)
            entity_brief_block = f"{entity_brief}\n\n" if entity_brief else ""
        else:
            entity_brief_block = ""
        messages_assemble = self.llm.as_chat(
            system=self.prompts.beat_assemble_system.format(chapter_count=chapter_count),
            user=self.prompts.beat_assemble_user.format(
                volume_title=vol_title,
                volume_arc=arc,
                volume_ending=ending,
                entity_brief_block=entity_brief_block,
                beat_count=len(raw_beats),
                chapter_count=chapter_count,
                beats_json=beats_json,
            ),
        )
        with self.trace.begin("beat_assemble", project=self.project_name, volume=number) as t:
            assemble_data = self.llm.generate_json(
                messages_assemble, temperature=1.0, max_tokens=16000,
            )
            t.record(messages_assemble, assemble_data, model=self.llm.default_model)

        chapter_map, beat_pool = _parse_assemble_from_raw(assemble_data, raw_beats)

        yield {"event": "step", "data": {
            "step": pipeline_step, "status": "running", "phase": "refining",
            "message": f"正在为 {len(chapter_map)} 章生成细场景…",
        }}

        # --- Per-chapter micro-scenes ---
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

        beat_data = VolumeBeatData(
            volume=number, step=pipeline_step,
            raw_beats=raw_beats,
            refined_beats=[],
            chapter_map=chapter_map,
        )
        self.outline.save_volume_beats(beat_data)

        for ch in chapters:
            self.outline.write_chapter(ch)
        self.outline.sync_volume_chapters(number)

        yield {"event": "step", "data": {
            "step": pipeline_step, "status": "done",
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
                entity_brief_block=(
                    f"{self._format_planning_entity_brief(
                        [entity for beat in chapter_beats for entity in beat.entities],
                        volume=number,
                    )}\n\n"
                    if self.planning_entities is not None
                    else ""
                ),
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
                data = self.llm.generate_json(messages, temperature=1.0, max_tokens=8000)
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
        if self.planning_entities is not None:
            self._sync_planning_entities(
                story_context=(
                    f"全书梗概：\n{synopsis}\n\n"
                    f"本卷大纲：\n{volume_arc}\n\n"
                    f"已发生章节：\n{_format_prev_chapters(prev_before[-8:]) or '（尚无）'}"
                ),
                source="story_backfill",
                volume=volume,
            )
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
            number,
            result,
            volume=volume,
            title=title,
            codex=self.codex,
            planning=self.planning_entities,
        )
        self._apply_planning_entity_changes(result, source="chapter_plan")

        # Preserve the existing summary so regeneration doesn't wipe it.
        if current_chapter and current_chapter.summary.strip():
            chapter.summary = current_chapter.summary

        # Collect diagnostics about new vs reused ids.
        resolved_ids: list[str] = []
        new_ids: list[str] = []
        if self.codex is not None:
            all_ids = chapter.all_entities()
            if self.planning_entities is not None:
                resolved_ids, id_warnings = self.planning_entities.resolve_entry_ids(
                    all_ids, codex=self.codex,
                )
                warnings.extend(id_warnings)
            else:
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

    def sync_planning_entities(self, *, volume: int | None = None) -> dict[str, object]:
        """Manually reconcile the author-side entity network from story state."""
        if self.planning_entities is None:
            return {}
        chapters = self.outline.list_chapters()
        volume_outline = self.outline.read_volume(volume) if volume is not None else None
        story_context = (
            f"全书梗概：\n{self.outline.read_synopsis().strip()}\n\n"
            f"本卷大纲：\n{volume_outline.arc if volume_outline else '（未指定）'}\n\n"
            f"已发生章节：\n{_format_prev_chapters(chapters[-8:]) or '（尚无）'}"
        )
        return self._sync_planning_entities(
            story_context=story_context,
            source="story_backfill",
            volume=volume,
        )

    def _sync_planning_entities(
        self,
        *,
        story_context: str,
        source: str,
        volume: int | None = None,
    ) -> dict[str, object]:
        """Ask the author-side entity service to reconcile existing story facts.

        This is intentionally separate from Codex enrichment: its output is
        author-only and may contain motivations or unrevealed truths.
        """
        if self.planning_entities is None:
            return {}
        network = self.planning_entities.render_brief(volume_number=volume)
        messages = self.llm.as_chat(
            system=self.prompts.entity_sync_system,
            user=self.prompts.entity_sync_user.format(
                entity_network=network,
                story_context=story_context or "（尚无已发生剧情，请只建立确有必要的初始主体。）",
            ),
        )
        with self.trace.begin(
            "planning_entity_sync",
            project=self.project_name,
            volume=volume,
            source=source,
        ) as trace:
            data = self.llm.generate_json(messages, temperature=0.4)
            trace.record(messages, data, model=self.llm.default_model)
        raw_entries = data.get("entries") if isinstance(data, dict) else []
        if not isinstance(raw_entries, list):
            raw_entries = []
        result = self.planning_entities.apply_foundation_entries(
            raw_entries,
            source=source,
            require_existence=True,
        )
        changes = PlanningCodexChanges.from_payload(data)
        if changes.relationships:
            relation_result = self.planning_entities.reconcile(
                PlanningCodexChanges(relationships=changes.relationships),
                source=source,
            )
            result.created_relationships.extend(relation_result.created_relationships)
            result.updated_relationships.extend(relation_result.updated_relationships)
            result.skipped_relationships.extend(relation_result.skipped_relationships)
        return result.model_dump()

    def _apply_planning_entity_changes(
        self, data: dict, *, source: str
    ) -> dict[str, object]:
        """Apply optional entity changes embedded in a volume or chapter plan."""
        if self.planning_entities is None:
            return {}
        changes = PlanningCodexChanges.from_payload(data.get("entity_changes"))
        # Legacy embedded changes may update known entries, but may not create
        # new existences because they carry no story-anchor evidence.
        known_ids = {
            entry.id for entry in self.planning_entities.store.list_entries()
        }
        changes.entries = [
            proposal for proposal in changes.entries if proposal.id in known_ids
        ]
        changes.relationships = [
            proposal
            for proposal in changes.relationships
            if (
                proposal.resolved_source_id() in known_ids
                and proposal.resolved_target_id() in known_ids
            )
        ]
        return self.planning_entities.reconcile(changes, source=source).model_dump()

    def _format_planning_entity_brief(
        self,
        entity_ids: list[str] | None = None,
        *,
        volume: int | None = None,
    ) -> str:
        if self.planning_entities is None:
            return ""
        return self.planning_entities.render_brief(entity_ids, volume_number=volume)

    def _format_revealed_codex_index(self) -> str:
        if self.codex is None:
            return "（无已揭示设定集）"
        entries = list(self.codex.iter_all())
        if not entries:
            return "（无已揭示设定集）"
        lines = []
        for e in entries[:40]:
            alias_str = f"（别名：{'、'.join(e.aliases)}）" if e.aliases else ""
            lines.append(f"  - {e.id}：{e.name}{alias_str}  [{e.type}]")
        return "\n".join(lines)

    def _format_entity_registry(
        self,
        entry_ids: list[str] | None = None,
        *,
        volume: int | None = None,
        full: bool = False,
    ) -> str:
        """Build combined author-side and reader-side entity context."""
        blocks: list[str] = []
        if self.planning_entities is not None:
            if full:
                if entry_ids is not None:
                    planning_brief = self.planning_entities.render_entries_full(
                        entry_ids, volume_number=volume,
                    )
                else:
                    planning_brief = self.planning_entities.render_full(
                        volume_number=volume,
                    )
            else:
                planning_brief = self._format_planning_entity_brief(
                    entry_ids, volume=volume,
                )
            if planning_brief:
                blocks.append(planning_brief)
        revealed = self._format_revealed_codex_index()
        if revealed and revealed != "（无已揭示设定集）":
            blocks.append(f"已揭示设定集索引（读者已知事实与别名对齐）：\n{revealed}")
        return "\n\n".join(blocks)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _planning_type_label(entry_type: str) -> str:
    return {
        "worldbuilding": "世界观",
        "timeline": "时间线",
        "faction": "势力",
        "location": "地点",
        "character": "角色",
        "item": "物品",
    }.get(entry_type, entry_type)


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


def _format_framework_block(framework: VolumeFramework) -> str:
    """Render a volume writing framework for downstream prompts."""
    lens = framework.reader_lens
    craft = framework.craft_focus
    lines = [
        "【本卷写作框架】",
        f"总述：{framework.casting_note or '（无）'}",
        "",
        "## 读者透镜",
        f"当前视角：{lens.current_perspective or '（无）'}",
        f"读者期待：{lens.what_they_want or '（无）'}",
    ]
    if lens.reveal_debts:
        lines.append("揭示债务：")
        lines.extend(f"- {d}" for d in lens.reveal_debts)
    lines.extend([
        "",
        "## 写作手法重心",
        f"冲突：{craft.conflict or '（无）'}",
        f"反转：{craft.reversal or '（无）'}",
        f"发展：{craft.development or '（无）'}",
        f"悬疑：{craft.suspense or '（无）'}",
        f"其他：{craft.other or '（无）'}",
        "",
        "## 舞台",
    ])
    if not framework.stages:
        lines.append("（无）")
    for stage in framework.stages:
        lines.append(f"### {stage.id}")
        lines.append(f"为何此舞台：{stage.why_this_stage}")
        lines.append(f"舞台压力：{stage.dramatic_pressure}")
    lines.extend(["", "## 出场"])
    if not framework.cast:
        lines.append("（无）")
    for entry in framework.cast:
        lines.append(f"### {entry.id}（{entry.billing}）")
        lines.append(f"处境与动机：{entry.situation}")
        lines.append(f"剧情影响：{entry.dramatic_impact}")
    if framework.involved_ids:
        lines.extend([
            "",
            f"涉及实体 id：{', '.join(framework.involved_ids)}",
        ])
    return "\n".join(lines) + "\n\n"


_VALID_BILLINGS = frozenset({
    "lead", "supporting", "antagonist", "cameo", "mentioned",
})


def _parse_volume_framework(
    data: dict,
    *,
    volume_number: int,
    known_ids: set[str],
) -> tuple[VolumeFramework, list[str]]:
    """Parse Step1 framework JSON; drop unknown ids and strip outline fields."""
    warnings: list[str] = []
    for banned in ("title", "arc", "ending", "chapter_count"):
        if banned in data and data.get(banned) not in (None, ""):
            warnings.append(f"写作框架输出含禁止字段 {banned}，已忽略")

    lens_raw = data.get("reader_lens") if isinstance(data.get("reader_lens"), dict) else {}
    debts = lens_raw.get("reveal_debts") or []
    if not isinstance(debts, list):
        debts = [str(debts)]
    reader_lens = FrameworkReaderLens(
        current_perspective=str(lens_raw.get("current_perspective") or "").strip(),
        what_they_want=str(lens_raw.get("what_they_want") or "").strip(),
        reveal_debts=[str(d).strip() for d in debts if str(d).strip()],
    )

    craft_raw = data.get("craft_focus") if isinstance(data.get("craft_focus"), dict) else {}
    craft_focus = FrameworkCraftFocus(
        conflict=str(craft_raw.get("conflict") or "").strip(),
        reversal=str(craft_raw.get("reversal") or "").strip(),
        development=str(craft_raw.get("development") or "").strip(),
        suspense=str(craft_raw.get("suspense") or "").strip(),
        other=str(craft_raw.get("other") or "").strip(),
    )

    stages: list[FrameworkStage] = []
    seen_stage_ids: set[str] = set()
    for item in data.get("stages") or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        if not sid:
            continue
        if known_ids and sid not in known_ids:
            warnings.append(f"舞台 id 未知，已丢弃：{sid}")
            continue
        if sid in seen_stage_ids:
            warnings.append(f"舞台 id 重复，已合并保留首条：{sid}")
            continue
        seen_stage_ids.add(sid)
        stages.append(FrameworkStage(
            id=sid,
            why_this_stage=str(item.get("why_this_stage") or "").strip(),
            dramatic_pressure=str(item.get("dramatic_pressure") or "").strip(),
        ))
    if len(stages) > 6:
        warnings.append(f"舞台数量 {len(stages)} 超过软上限 6，已截断")
        stages = stages[:6]

    cast: list[FrameworkCastEntry] = []
    for item in data.get("cast") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            continue
        if known_ids and cid not in known_ids:
            warnings.append(f"出场 id 未知，已丢弃：{cid}")
            continue
        billing = str(item.get("billing") or "supporting").strip().lower()
        if billing not in _VALID_BILLINGS:
            warnings.append(f"billing 非法 {billing!r}（{cid}），已改为 supporting")
            billing = "supporting"
        cast.append(FrameworkCastEntry(
            id=cid,
            billing=billing,
            situation=str(item.get("situation") or "").strip(),
            dramatic_impact=str(item.get("dramatic_impact") or "").strip(),
        ))
    if len(cast) > 12:
        warnings.append(f"出场数量 {len(cast)} 超过软上限 12，已截断")
        cast = cast[:12]

    involved_raw = data.get("involved_ids") or []
    if not isinstance(involved_raw, list):
        involved_raw = []
    involved_ids = [str(x).strip() for x in involved_raw if str(x).strip()]
    if known_ids:
        filtered = [i for i in involved_ids if i in known_ids]
        for dropped in set(involved_ids) - set(filtered):
            warnings.append(f"involved_ids 含未知 id，已丢弃：{dropped}")
        involved_ids = filtered

    framework = VolumeFramework(
        volume_number=volume_number,
        reader_lens=reader_lens,
        craft_focus=craft_focus,
        stages=stages,
        cast=cast,
        casting_note=str(data.get("casting_note") or "").strip(),
        involved_ids=involved_ids,
    )
    if not framework.cast and not framework.stages:
        warnings.append("写作框架未选出任何出场或舞台")
    return framework, warnings


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


def _parse_chapter_json(
    number: int,
    data: dict,
    *,
    volume: int | None,
    title: str,
    codex: CodexStore | None = None,
    planning: PlanningCodexService | None = None,
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
        ids = [str(x) for x in raw_ids if str(x).strip()]
        if planning is not None:
            resolved, w = planning.resolve_entry_ids(ids, codex=codex)
            warnings.extend(w)
            return resolved
        if codex is None:
            return ids
        from ..codex import resolve_entity_ids

        resolved, res_log = resolve_entity_ids(ids, codex)
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
def _parse_raw_beats(
    data: dict,
    *,
    codex: CodexStore | None = None,
    planning: PlanningCodexService | None = None,
) -> tuple[list[RawBeat], list[str]]:
    """Parse the LLM's beat chain JSON into RawBeat objects."""
    warnings: list[str] = []
    raw = data.get("beats")
    if not isinstance(raw, list):
        raise ValueError("beat 链规划缺少 beats 数组")

    beats: list[RawBeat] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        beat_id = str(item.get("id", f"b{i + 1:02d}"))
        entities = [str(x) for x in (item.get("entities") or []) if str(x).strip()]
        if entities:
            if planning is not None:
                entities, w = planning.resolve_entry_ids(entities, codex=codex)
                warnings.extend(w)
            elif codex is not None:
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
    return beats, warnings


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
        action = str(s.get("action", "")).strip()
        event = str(s.get("event", "")).strip()
        intent = str(s.get("intent", "")).strip()
        if not intent:
            intent = event or action
        scenes.append(MicroScene(
            intent=intent,
            sensory=str(s.get("sensory", "")).strip(),
            action=action,
            dialogue=str(s.get("dialogue", "")).strip(),
            event=event,
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
