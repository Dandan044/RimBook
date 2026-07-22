"""Budgeted breadth-first expansion of the author-side planning codex."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import yaml
from pydantic import BaseModel, Field, field_validator

from ..versioning import atomic_write
from .models import PlanningCodexChanges, RelationshipProposal
from .service import PlanningCodexService, ReconcileResult

__all__ = [
    "ExpansionBudget",
    "ExpansionCandidate",
    "ExpansionRunState",
    "WorldExpander",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExpansionBudget(BaseModel):
    """Hard limits derived from a user-facing divergence coefficient."""

    coefficient: int = Field(ge=1, le=4)
    max_depth: int = Field(ge=0, le=3)
    max_new_per_seed: int = Field(ge=0, le=4)
    max_new_per_run: int = Field(ge=0, le=55)
    max_candidates_per_seed: int = Field(ge=0, le=12)
    max_relationships_per_seed: int = Field(ge=0, le=6)
    max_llm_calls: int = Field(ge=0, le=160)
    min_relatedness: float = Field(ge=0, le=1)

    @classmethod
    def for_coefficient(cls, coefficient: int) -> "ExpansionBudget":
        presets = {
            1: (0, 0, 0, 0, 0, 0, 1.0),
            2: (1, 2, 12, 6, 3, 40, 0.62),
            3: (2, 3, 28, 9, 4, 75, 0.57),
            4: (3, 4, 55, 12, 6, 130, 0.52),
        }
        if coefficient not in presets:
            raise ValueError("发散系数必须是 1–4")
        (
            max_depth,
            max_new_per_seed,
            max_new_per_run,
            max_candidates_per_seed,
            max_relationships_per_seed,
            max_llm_calls,
            min_relatedness,
        ) = presets[coefficient]
        return cls(
            coefficient=coefficient,
            max_depth=max_depth,
            max_new_per_seed=max_new_per_seed,
            max_new_per_run=max_new_per_run,
            max_candidates_per_seed=max_candidates_per_seed,
            max_relationships_per_seed=max_relationships_per_seed,
            max_llm_calls=max_llm_calls,
            min_relatedness=min_relatedness,
        )


class ExpansionCandidate(BaseModel):
    """One possible existence mined from a completed setting detail."""

    provisional_id: str
    name: str
    type: str
    source_entry_ids: list[str] = Field(default_factory=list)
    evidence: str = ""
    importance: str = ""
    relationship_type: str = "related"
    relatedness: float = Field(default=0.5, ge=0, le=1)
    exists_at_anchor: bool = True
    existence_reason: str = ""
    formation_event: dict | None = None
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    surface_summary: str = ""
    secret_truth: str = ""
    narrative_role: str = ""
    reveal_strategy: str = ""
    details: dict = Field(default_factory=dict)
    existing_match_id: str = ""

    @field_validator("provisional_id", "name")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("候选 ID 与名称不能为空")
        return value

    def as_entry_payload(self, *, depth: int, run_id: str) -> dict:
        details = {
            **self.details,
            "expansion_depth": depth,
            "source_entry_ids": list(self.source_entry_ids),
            "expansion_run_id": run_id,
            "expansion_evidence": self.evidence,
        }
        return {
            "id": self.provisional_id,
            "name": self.name,
            "type": self.type,
            "aliases": self.aliases,
            "tags": [*self.tags, "world_expand"],
            "surface_summary": self.surface_summary,
            "secret_truth": self.secret_truth,
            "narrative_role": self.narrative_role,
            "reveal_strategy": self.reveal_strategy,
            "details": details,
            "exists_at_anchor": self.exists_at_anchor,
            "existence_reason": self.existence_reason,
            "formation_event": self.formation_event,
        }


class ExpansionRunState(BaseModel):
    run_id: str
    coefficient: int
    current_depth: int = 1
    seed_ids: list[str] = Field(default_factory=list)
    processed_seed_ids: list[str] = Field(default_factory=list)
    created_entry_ids: list[str] = Field(default_factory=list)
    created_relationship_ids: list[str] = Field(default_factory=list)
    llm_calls_used: int = 0
    complete: bool = False
    stopped_reason: str = ""
    updated_at: str = ""


class WorldExpander:
    """Deterministic budget, dedup and checkpoint layer around LLM discovery."""

    def __init__(self, service: PlanningCodexService) -> None:
        self.service = service
        self.store = service.store

    def start_or_resume(
        self,
        *,
        coefficient: int,
        seed_ids: list[str],
    ) -> ExpansionRunState:
        existing = self.load_state()
        if (
            existing is not None
            and not existing.complete
            and existing.coefficient == coefficient
        ):
            return existing
        state = ExpansionRunState(
            run_id=f"expand-{uuid.uuid4().hex[:12]}",
            coefficient=coefficient,
            seed_ids=list(dict.fromkeys(seed_ids)),
        )
        self.save_state(state)
        return state

    def load_state(self) -> ExpansionRunState | None:
        path = self.store.paths.planning_expansion_state_file
        if not path.exists():
            return None
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return ExpansionRunState.model_validate(raw) if isinstance(raw, dict) else None

    def save_state(self, state: ExpansionRunState) -> None:
        state.updated_at = _now()
        atomic_write(
            self.store.paths.planning_expansion_state_file,
            yaml.safe_dump(
                state.model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=False,
            ),
        )

    def deduplicate(
        self,
        candidates: list[ExpansionCandidate],
    ) -> tuple[list[ExpansionCandidate], list[str]]:
        entries = self.store.list_entries()
        by_id = {entry.id: entry for entry in entries}
        by_identity: dict[tuple[str, str], str] = {}
        for entry in entries:
            for value in [entry.name, *entry.aliases]:
                by_identity[(entry.type, _normalize_name(value))] = entry.id

        accepted: list[ExpansionCandidate] = []
        warnings: list[str] = []
        seen_candidates: set[tuple[str, str]] = set()
        for candidate in candidates:
            identity = (candidate.type, _normalize_name(candidate.name))
            if candidate.provisional_id in by_id:
                candidate.existing_match_id = candidate.provisional_id
            elif identity in by_identity:
                candidate.existing_match_id = by_identity[identity]
            if identity in seen_candidates:
                warnings.append(f"跳过重复候选: {candidate.name}")
                continue
            seen_candidates.add(identity)
            accepted.append(candidate)
        return accepted, warnings

    def select(
        self,
        candidates: list[ExpansionCandidate],
        *,
        budget: ExpansionBudget,
        state: ExpansionRunState,
    ) -> list[ExpansionCandidate]:
        remaining = max(
            budget.max_new_per_run - len(state.created_entry_ids),
            0,
        )
        ranked = sorted(
            (
                candidate
                for candidate in candidates
                if candidate.relatedness >= budget.min_relatedness
            ),
            key=lambda item: (
                bool(item.existing_match_id),
                item.relatedness,
                len(item.source_entry_ids),
            ),
            reverse=True,
        )
        per_seed: dict[str, int] = {}
        selected: list[ExpansionCandidate] = []
        new_count = 0
        for candidate in ranked:
            source = candidate.source_entry_ids[0] if candidate.source_entry_ids else ""
            if source and per_seed.get(source, 0) >= budget.max_new_per_seed:
                continue
            is_new = not candidate.existing_match_id
            if is_new and new_count >= remaining:
                continue
            selected.append(candidate)
            if source:
                per_seed[source] = per_seed.get(source, 0) + 1
            if is_new:
                new_count += 1
        return selected

    def materialize(
        self,
        candidates: list[ExpansionCandidate],
        *,
        depth: int,
        state: ExpansionRunState,
    ) -> tuple[list[str], ReconcileResult]:
        result = ReconcileResult()
        new_candidates = [
            candidate for candidate in candidates if not candidate.existing_match_id
        ]
        entry_result = self.service.apply_foundation_entries(
            [
                candidate.as_entry_payload(depth=depth, run_id=state.run_id)
                for candidate in new_candidates
            ],
            source="world_expand",
            require_existence=True,
        )
        _merge_results(result, entry_result)

        known_ids = {entry.id for entry in self.store.list_entries()}
        relations: list[RelationshipProposal] = []
        for candidate in candidates:
            target_id = candidate.existing_match_id or candidate.provisional_id
            if target_id not in known_ids:
                continue
            for source_id in candidate.source_entry_ids:
                if source_id not in known_ids or source_id == target_id:
                    continue
                relation_id = f"expand_{_slug(source_id)}_{_slug(target_id)}"
                relations.append(
                    RelationshipProposal(
                        id=relation_id,
                        source_id=source_id,
                        target_id=target_id,
                        relationship_type=candidate.relationship_type or "related",
                        tags=["implied", f"expand:d{depth}", state.run_id],
                        status=candidate.importance,
                    )
                )
        if relations:
            relation_result = self.service.reconcile(
                PlanningCodexChanges(relationships=relations),
                source="world_expand",
            )
            _merge_results(result, relation_result)

        created = list(result.created_entries)
        state.created_entry_ids.extend(
            entry_id for entry_id in created if entry_id not in state.created_entry_ids
        )
        state.created_relationship_ids.extend(
            relation_id
            for relation_id in result.created_relationships
            if relation_id not in state.created_relationship_ids
        )
        self.save_state(state)
        return created, result


def _merge_results(target: ReconcileResult, source: ReconcileResult) -> None:
    for field_name in (
        "created_entries",
        "updated_entries",
        "created_relationships",
        "updated_relationships",
        "skipped_locked_fields",
        "skipped_relationships",
        "warnings",
    ):
        getattr(target, field_name).extend(getattr(source, field_name))


def _normalize_name(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.strip().casefold())


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "_", value).strip("_")
