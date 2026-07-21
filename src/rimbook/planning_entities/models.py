"""Author-side planning entity and relationship models.

These models deliberately live outside ``codex``: they may contain unrevealed
motives and future arc information that must not enter reader-facing context.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

__all__ = [
    "EntityArc",
    "RelationshipArc",
    "PlanningEntity",
    "EntityRelationship",
    "EntityNetwork",
    "PlanningEntityProposal",
    "RelationshipProposal",
    "EntityNetworkChanges",
]


class EntityArc(BaseModel):
    """The author-known long-running movement of one planning entity."""

    start: str = ""
    current: str = ""
    destination: str = ""


class RelationshipArc(BaseModel):
    """How an author intends a relationship to change."""

    start: str = ""
    current: str = ""
    destination: str = ""


class PlanningEntity(BaseModel):
    """A story-driving entity as understood by the author."""

    id: str
    name: str
    kind: str = Field(default="character", description="Human, non-human, or other acting entity.")
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    story_role: str = ""
    surface_goal: str = ""
    inner_need: str = ""
    fear: str = ""
    values: str = ""
    flaw: str = ""
    secret: str = ""
    capabilities: str = ""
    limitations: str = ""
    voice: str = ""
    action_style: str = ""
    arc: EntityArc = Field(default_factory=EntityArc)
    volume_roles: dict[str, str] = Field(default_factory=dict)
    codex_ref: str = ""
    field_locks: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", description="manual, story_backfill, volume_plan, or chapter_plan")
    updated_at: str = ""

    @field_validator("id", "name")
    @classmethod
    def require_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("实体 id 和名称不能为空")
        return value

    @field_validator("field_locks")
    @classmethod
    def normalize_locks(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    def is_locked(self, field_name: str) -> bool:
        return field_name in self.field_locks


class EntityRelationship(BaseModel):
    """A directional, author-side relationship between two planning entities."""

    id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str = "related"
    tags: list[str] = Field(default_factory=list)
    status: str = ""
    source_goal: str = ""
    target_goal: str = ""
    stakes: str = ""
    conflict: str = ""
    secret: str = ""
    arc: RelationshipArc = Field(default_factory=RelationshipArc)
    field_locks: list[str] = Field(default_factory=list)
    source: str = "manual"
    updated_at: str = ""

    @field_validator("id", "source_entity_id", "target_entity_id")
    @classmethod
    def require_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("关系标识和实体引用不能为空")
        return value

    @field_validator("field_locks")
    @classmethod
    def normalize_locks(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    def is_locked(self, field_name: str) -> bool:
        return field_name in self.field_locks


class EntityNetwork(BaseModel):
    """The complete author-side entity network persisted in one YAML file."""

    version: int = 1
    entities: list[PlanningEntity] = Field(default_factory=list)
    relationships: list[EntityRelationship] = Field(default_factory=list)
    updated_at: str = ""


class PlanningEntityProposal(BaseModel):
    """A partial AI or API update; ``None`` means leave the field unchanged."""

    id: str
    name: str | None = None
    kind: str | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None
    story_role: str | None = None
    surface_goal: str | None = None
    inner_need: str | None = None
    fear: str | None = None
    values: str | None = None
    flaw: str | None = None
    secret: str | None = None
    capabilities: str | None = None
    limitations: str | None = None
    voice: str | None = None
    action_style: str | None = None
    arc: EntityArc | None = None
    volume_roles: dict[str, str] | None = None
    codex_ref: str | None = None


class RelationshipProposal(BaseModel):
    """A partial AI or API update for one relationship."""

    id: str
    source_entity_id: str | None = None
    target_entity_id: str | None = None
    relationship_type: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    source_goal: str | None = None
    target_goal: str | None = None
    stakes: str | None = None
    conflict: str | None = None
    secret: str | None = None
    arc: RelationshipArc | None = None


class EntityNetworkChanges(BaseModel):
    """Structured planning updates returned by an entity synchronization LLM."""

    entities: list[PlanningEntityProposal] = Field(default_factory=list)
    relationships: list[RelationshipProposal] = Field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_payload(cls, payload: Any) -> "EntityNetworkChanges":
        """Parse only valid structured proposals from an optional LLM block.

        ``entity_changes`` enriches planning but must never prevent the volume
        or chapter plan from completing. Some providers return natural-language
        summaries in its arrays despite the JSON schema, so malformed entries
        are ignored individually instead of failing the entire pipeline.
        """
        if not isinstance(payload, dict):
            return cls()

        entities: list[PlanningEntityProposal] = []
        for item in payload.get("entities") or []:
            if not isinstance(item, dict):
                continue
            try:
                entities.append(PlanningEntityProposal.model_validate(item))
            except ValidationError:
                continue

        relationships: list[RelationshipProposal] = []
        for item in payload.get("relationships") or []:
            if not isinstance(item, dict):
                continue
            try:
                relationships.append(RelationshipProposal.model_validate(item))
            except ValidationError:
                continue

        return cls(
            entities=entities,
            relationships=relationships,
            notes=str(payload.get("notes") or ""),
        )
