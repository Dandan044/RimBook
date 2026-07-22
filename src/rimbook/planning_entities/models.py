"""Author-side planning codex models (full setting bible).

These models deliberately live outside ``codex``: they may contain unrevealed
motives, histories, and secret agendas that must not enter reader-facing
context.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field, ValidationError, computed_field, field_validator, model_validator

from ..codex.models import VALID_TYPES

__all__ = [
    "EntityArc",
    "RelationshipArc",
    "PlanningCodexEntry",
    "PlanningRelationship",
    "PlanningEntity",
    "EntityRelationship",
    "EntityNetwork",
    "PlanningCodexProposal",
    "PlanningEntityProposal",
    "RelationshipProposal",
    "PlanningCodexChanges",
    "EntityNetworkChanges",
]

_LOCK_TO_ENTRY = {
    "surface_goal": "surface_summary",
    "secret": "secret_truth",
    "story_role": "narrative_role",
    "codex_ref": "revealed_ref",
}
_LOCK_TO_ENTITY = {v: k for k, v in _LOCK_TO_ENTRY.items()}


def _map_locks_to_entry(locks: list[str]) -> list[str]:
    return list(dict.fromkeys(_LOCK_TO_ENTRY.get(item, item) for item in locks))


def _map_locks_to_entity(locks: list[str]) -> list[str]:
    return list(dict.fromkeys(_LOCK_TO_ENTITY.get(item, item) for item in locks))


class EntityArc(BaseModel):
    """The author-known long-running movement of one planning entry."""

    start: str = ""
    current: str = ""
    destination: str = ""


class RelationshipArc(BaseModel):
    """How an author intends a relationship to change."""

    start: str = ""
    current: str = ""
    destination: str = ""


class PlanningCodexEntry(BaseModel):
    """A single author-side planning codex entry (any of six types)."""

    id: str
    name: str
    type: str = Field(default="character", description="One of VALID_TYPES.")
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    relationship_refs: list[str] = Field(default_factory=list)
    revealed_ref: str = Field(
        default="",
        description="Linked id in the revealed codex, if any.",
    )
    surface_summary: str = Field(
        default="",
        description="Public-facing summary the reader may eventually see.",
    )
    secret_truth: str = Field(
        default="",
        description="Author-only truth not yet revealed to the reader.",
    )
    narrative_role: str = Field(default="", description="Story function of this entry.")
    reveal_strategy: str = Field(
        default="",
        description="The hook and narrative means by which this existence first enters prose.",
    )
    detail: str = Field(
        default="",
        description="Long-form Markdown history and background of this existence.",
    )
    volume_roles: dict[str, str] = Field(default_factory=dict)
    field_locks: list[str] = Field(default_factory=list)
    source: str = Field(
        default="manual",
        description="manual, foundation, volume_cast, story_backfill, volume_plan, or chapter_plan",
    )
    updated_at: str = ""
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific fields (motives, strategic value, hidden abilities, etc.).",
    )
    body: str = Field(default="", description="Optional free-form Markdown notes.")

    @field_validator("id", "name")
    @classmethod
    def require_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("条目 id 和名称不能为空")
        return value

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        value = value.strip()
        if value not in VALID_TYPES:
            raise ValueError(f"无效的类型 {value!r}，必须是 {VALID_TYPES} 之一")
        return value

    @field_validator("field_locks")
    @classmethod
    def normalize_locks(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    def is_locked(self, field_name: str) -> bool:
        return field_name in self.field_locks

    def to_planning_entity(self) -> "PlanningEntity":
        """Convert a character entry to the legacy PlanningEntity shape."""
        arc_data = self.details.get("arc") or {}
        if isinstance(arc_data, EntityArc):
            arc = arc_data
        elif isinstance(arc_data, dict):
            arc = EntityArc(**arc_data)
        else:
            arc = EntityArc(start=str(arc_data) if arc_data else "")
        return PlanningEntity(
            id=self.id,
            name=self.name,
            kind=str(self.details.get("kind") or "character"),
            aliases=list(self.aliases),
            tags=list(self.tags),
            story_role=self.narrative_role or str(self.details.get("story_role") or ""),
            surface_goal=self.surface_summary or str(self.details.get("surface_goal") or ""),
            inner_need=str(self.details.get("inner_need") or ""),
            fear=str(self.details.get("fear") or ""),
            values=str(self.details.get("values") or ""),
            flaw=str(self.details.get("flaw") or ""),
            secret=self.secret_truth,
            capabilities=str(self.details.get("capabilities") or ""),
            limitations=str(self.details.get("limitations") or ""),
            voice=str(self.details.get("voice") or ""),
            action_style=str(self.details.get("action_style") or ""),
            arc=arc,
            volume_roles=dict(self.volume_roles),
            codex_ref=self.revealed_ref,
            field_locks=_map_locks_to_entity(self.field_locks),
            source=self.source,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_planning_entity(cls, entity: "PlanningEntity") -> "PlanningCodexEntry":
        """Convert legacy PlanningEntity to a character PlanningCodexEntry."""
        arc = entity.arc
        details = {
            "kind": entity.kind,
            "story_role": entity.story_role,
            "surface_goal": entity.surface_goal,
            "inner_need": entity.inner_need,
            "fear": entity.fear,
            "values": entity.values,
            "flaw": entity.flaw,
            "capabilities": entity.capabilities,
            "limitations": entity.limitations,
            "voice": entity.voice,
            "action_style": entity.action_style,
            "arc": arc.model_dump(mode="json"),
        }
        return cls(
            id=entity.id,
            name=entity.name,
            type="character",
            aliases=list(entity.aliases),
            tags=list(entity.tags),
            narrative_role=entity.story_role,
            surface_summary=entity.surface_goal,
            secret_truth=entity.secret,
            volume_roles=dict(entity.volume_roles),
            revealed_ref=entity.codex_ref,
            field_locks=_map_locks_to_entry(entity.field_locks),
            source=entity.source,
            updated_at=entity.updated_at,
            details=details,
        )


class PlanningEntity(BaseModel):
    """Legacy character-focused model; kept for API backward compatibility."""

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


class PlanningRelationship(BaseModel):
    """A directional, cross-type relationship between two planning entries."""

    id: str
    source_id: str = Field(validation_alias=AliasChoices("source_id", "source_entity_id"))
    target_id: str = Field(validation_alias=AliasChoices("target_id", "target_entity_id"))
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

    @field_validator("id", "source_id", "target_id")
    @classmethod
    def require_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("关系标识和条目引用不能为空")
        return value

    @field_validator("field_locks")
    @classmethod
    def normalize_locks(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    def is_locked(self, field_name: str) -> bool:
        return field_name in self.field_locks

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_entity_id(self) -> str:
        return self.source_id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def target_entity_id(self) -> str:
        return self.target_id


# Backward-compatible alias
EntityRelationship = PlanningRelationship


class EntityNetwork(BaseModel):
    """Snapshot of the author-side planning network (API / legacy compat)."""

    version: int = 2
    entries: list[PlanningCodexEntry] = Field(default_factory=list)
    relationships: list[PlanningRelationship] = Field(default_factory=list)
    updated_at: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def entities(self) -> list[PlanningEntity]:
        """Character entries as legacy PlanningEntity objects (API compat)."""
        return [
            entry.to_planning_entity()
            for entry in self.entries
            if entry.type == "character"
        ]


class PlanningCodexProposal(BaseModel):
    """A partial AI or API update; ``None`` means leave the field unchanged."""

    id: str
    name: str | None = None
    type: str | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None
    revealed_ref: str | None = None
    surface_summary: str | None = None
    secret_truth: str | None = None
    narrative_role: str | None = None
    reveal_strategy: str | None = None
    detail: str | None = None
    volume_roles: dict[str, str] | None = None
    details: dict[str, Any] | None = None
    body: str | None = None


class PlanningEntityProposal(BaseModel):
    """Legacy character proposal; mapped to PlanningCodexProposal internally."""

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

    def to_codex_proposal(self) -> PlanningCodexProposal:
        details: dict[str, Any] = {}
        for key in (
            "kind", "story_role", "surface_goal", "inner_need", "fear", "values",
            "flaw", "capabilities", "limitations", "voice", "action_style",
        ):
            value = getattr(self, key)
            if value is not None:
                details[key] = value
        if self.arc is not None:
            details["arc"] = self.arc.model_dump(mode="json")
        return PlanningCodexProposal(
            id=self.id,
            name=self.name,
            type="character",
            aliases=self.aliases,
            tags=self.tags,
            revealed_ref=self.codex_ref,
            surface_summary=self.surface_goal,
            secret_truth=self.secret,
            narrative_role=self.story_role,
            volume_roles=self.volume_roles,
            details=details or None,
        )


class RelationshipProposal(BaseModel):
    """A partial AI or API update for one relationship."""

    id: str
    source_id: str | None = None
    target_id: str | None = None
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

    def resolved_source_id(self, fallback: str = "") -> str | None:
        return self.source_id or self.source_entity_id or fallback or None

    def resolved_target_id(self, fallback: str = "") -> str | None:
        return self.target_id or self.target_entity_id or fallback or None


class PlanningCodexChanges(BaseModel):
    """Structured planning updates for the full planning codex."""

    entries: list[PlanningCodexProposal] = Field(default_factory=list)
    relationships: list[RelationshipProposal] = Field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_payload(cls, payload: Any) -> "PlanningCodexChanges":
        if not isinstance(payload, dict):
            return cls()

        entries: list[PlanningCodexProposal] = []
        for item in payload.get("entries") or payload.get("entities") or []:
            if not isinstance(item, dict):
                continue
            try:
                if "type" in item or "surface_summary" in item or "details" in item:
                    entries.append(PlanningCodexProposal.model_validate(item))
                else:
                    entries.append(PlanningEntityProposal.model_validate(item).to_codex_proposal())
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
            entries=entries,
            relationships=relationships,
            notes=str(payload.get("notes") or ""),
        )


class EntityNetworkChanges(PlanningCodexChanges):
    """Backward-compatible alias; accepts legacy ``entities`` input."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_entities(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("entries"):
            return data
        legacy = data.get("entities")
        if not legacy:
            return data
        entries: list[Any] = []
        for item in legacy:
            if isinstance(item, PlanningEntityProposal):
                entries.append(item.to_codex_proposal())
                continue
            if isinstance(item, PlanningCodexProposal):
                entries.append(item)
                continue
            if not isinstance(item, dict):
                continue
            try:
                if "type" in item or "surface_summary" in item or "details" in item:
                    entries.append(PlanningCodexProposal.model_validate(item))
                else:
                    entries.append(PlanningEntityProposal.model_validate(item).to_codex_proposal())
            except ValidationError:
                continue
        payload = dict(data)
        payload["entries"] = entries
        payload.pop("entities", None)
        return payload

    @property
    def entities(self) -> list[PlanningEntityProposal]:
        out: list[PlanningEntityProposal] = []
        for proposal in self.entries:
            if proposal.type not in (None, "character"):
                continue
            details = dict(proposal.details or {})
            arc = details.pop("arc", {}) or {}
            if isinstance(arc, dict):
                arc_obj = EntityArc(**arc)
            else:
                arc_obj = EntityArc()
            out.append(
                PlanningEntityProposal(
                    id=proposal.id,
                    name=proposal.name,
                    kind=details.get("kind"),
                    aliases=proposal.aliases,
                    tags=proposal.tags,
                    story_role=proposal.narrative_role or details.get("story_role"),
                    surface_goal=proposal.surface_summary or details.get("surface_goal"),
                    inner_need=details.get("inner_need"),
                    fear=details.get("fear"),
                    values=details.get("values"),
                    flaw=details.get("flaw"),
                    secret=proposal.secret_truth,
                    capabilities=details.get("capabilities"),
                    limitations=details.get("limitations"),
                    voice=details.get("voice"),
                    action_style=details.get("action_style"),
                    arc=arc_obj,
                    volume_roles=proposal.volume_roles,
                    codex_ref=proposal.revealed_ref,
                )
            )
        return out

    @classmethod
    def from_payload(cls, payload: Any) -> "EntityNetworkChanges":
        base = PlanningCodexChanges.from_payload(payload)
        return cls(entries=base.entries, relationships=base.relationships, notes=base.notes)
