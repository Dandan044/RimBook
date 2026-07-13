"""Per-entity current-state tracking.

The single most common consistency failure in LLM novels is an entity
"forgetting" where it is, what it knows, or what it's carrying. The
codex holds an entity's *static* profile; this module holds their
*current, mutable* state — and it's what the assembler injects so the model
writes them correctly.

State is stored as a single YAML file per entity under ``state/entities/``,
making it both machine-writable and human-inspectable.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from ..project import ProjectPaths
from ..versioning import atomic_write

__all__ = ["EntityState", "EntityStateStore", "KnowledgeItem", "PossessionItem"]


class KnowledgeItem(BaseModel):
    """A single fact an entity knows, with provenance metadata."""

    fact: str = Field(..., description="The knowledge content.")
    source_chapter: int = Field(default=0, ge=0, description="Chapter where this was learned.")
    confidence: str = Field(default="high", description="high | medium | low.")


class PossessionItem(BaseModel):
    """A single item an entity holds, with provenance metadata."""

    item: str = Field(..., description="The item name.")
    acquired_chapter: int = Field(default=0, ge=0, description="Chapter where this was acquired.")
    quantity: str = Field(default="", description="Optional quantity, e.g. '3卷'.")


class EntityState(BaseModel):
    """The mutable, current state of one entity."""

    entity_id: str
    location: str = Field(default="", description="Where the entity currently is.")
    knowledge: list[KnowledgeItem] = Field(
        default_factory=list,
        description="Key facts the entity has learned (plot-relevant), with provenance.",
    )
    possessions: list[PossessionItem] = Field(
        default_factory=list,
        description="Notable items the entity holds, with provenance.",
    )
    relationships: dict[str, str] = Field(
        default_factory=dict,
        description="entity_id -> short note on current standing (e.g. 'ally').",
    )
    status: str = Field(
        default="", description="Free-form current condition (injured, in disguise, ...)."
    )
    last_seen_chapter: int = Field(default=0, description="Chapter where last updated.")

    # ---- backward-compat validators ----
    @field_validator("knowledge", mode="before")
    @classmethod
    def _upgrade_knowledge(cls, v: Any) -> list[dict]:
        """Accept old-style ``list[str]`` and upgrade to ``list[KnowledgeItem]``."""
        if isinstance(v, list):
            return [
                {"fact": str(item)} if isinstance(item, str) else item
                for item in v
            ]
        return v or []

    @field_validator("possessions", mode="before")
    @classmethod
    def _upgrade_possessions(cls, v: Any) -> list[dict]:
        """Accept old-style ``list[str]`` and upgrade to ``list[PossessionItem]``."""
        if isinstance(v, list):
            return [
                {"item": str(item)} if isinstance(item, str) else item
                for item in v
            ]
        return v or []


class EntityStateStore:
    """Read & write :class:`EntityState` files under ``state/entities/``."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.dir = paths.state_dir / "entities"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, entity_id: str) -> Path:
        return self.dir / f"{entity_id}.yaml"

    def get(self, entity_id: str) -> EntityState:
        path = self._path(entity_id)
        if not path.exists():
            return EntityState(entity_id=entity_id)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("entity_id", entity_id)
        return EntityState.model_validate(data)

    def get_many(self, entity_ids: list[str]) -> list[EntityState]:
        return [self.get(eid) for eid in entity_ids]

    def save(self, state: EntityState) -> Path:
        path = self._path(state.entity_id)
        data = state.model_dump(mode="json")
        atomic_write(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        return path

    def all(self) -> list[EntityState]:
        out: list[EntityState] = []
        for path in sorted(self.dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            data.setdefault("entity_id", path.stem)
            try:
                out.append(EntityState.model_validate(data))
            except Exception:
                continue
        return out
