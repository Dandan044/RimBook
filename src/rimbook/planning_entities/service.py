"""Merge and prompt-context services for author-side planning entities."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    EntityNetworkChanges,
    EntityRelationship,
    PlanningEntity,
    PlanningEntityProposal,
    RelationshipProposal,
)
from .store import PlanningEntityStore

__all__ = ["EntityNetworkService", "ReconcileResult"]


@dataclass
class ReconcileResult:
    """A small, serializable summary of a network reconciliation."""

    created_entities: list[str] = field(default_factory=list)
    updated_entities: list[str] = field(default_factory=list)
    created_relationships: list[str] = field(default_factory=list)
    updated_relationships: list[str] = field(default_factory=list)
    skipped_locked_fields: list[str] = field(default_factory=list)
    skipped_relationships: list[str] = field(default_factory=list)

    @property
    def change_count(self) -> int:
        return sum(
            len(values)
            for values in (
                self.created_entities,
                self.updated_entities,
                self.created_relationships,
                self.updated_relationships,
            )
        )

    def model_dump(self) -> dict[str, object]:
        return {
            "created_entities": self.created_entities,
            "updated_entities": self.updated_entities,
            "created_relationships": self.created_relationships,
            "updated_relationships": self.updated_relationships,
            "skipped_locked_fields": self.skipped_locked_fields,
            "skipped_relationships": self.skipped_relationships,
            "change_count": self.change_count,
        }


class EntityNetworkService:
    """Applies AI proposals safely and renders compact planning context."""

    def __init__(self, store: PlanningEntityStore) -> None:
        self.store = store

    def reconcile(self, changes: EntityNetworkChanges, *, source: str) -> ReconcileResult:
        """Merge proposed changes while preserving every explicitly locked field."""
        result = ReconcileResult()
        network = self.store.read_network()
        entities = {entity.id: entity for entity in network.entities}
        relationships = {relation.id: relation for relation in network.relationships}

        for proposal in changes.entities:
            existing = entities.get(proposal.id)
            if existing is None:
                entity = self._new_entity(proposal, source)
                network.entities.append(entity)
                entities[entity.id] = entity
                result.created_entities.append(entity.id)
                continue
            if self._merge_entity(existing, proposal, result):
                existing.source = source
                result.updated_entities.append(existing.id)

        for proposal in changes.relationships:
            existing = relationships.get(proposal.id)
            if existing is None:
                relationship = self._new_relationship(proposal, source)
                if relationship is None or not self._relationship_endpoints_exist(relationship, entities):
                    result.skipped_relationships.append(proposal.id)
                    continue
                network.relationships.append(relationship)
                relationships[relationship.id] = relationship
                result.created_relationships.append(relationship.id)
                continue
            proposed_endpoints = (
                proposal.source_entity_id or existing.source_entity_id,
                proposal.target_entity_id or existing.target_entity_id,
            )
            if any(endpoint not in entities for endpoint in proposed_endpoints):
                result.skipped_relationships.append(proposal.id)
                continue
            if self._merge_relationship(existing, proposal, result):
                existing.source = source
                result.updated_relationships.append(existing.id)

        if result.change_count:
            self.store.write_network(network)
        return result

    def render_brief(
        self,
        entity_ids: list[str] | None = None,
        *,
        volume_number: int | None = None,
        max_entities: int = 12,
    ) -> str:
        """Render an author-only, token-bounded brief for planning prompts."""
        network = self.store.read_network()
        wanted = set(entity_ids or [])
        entities = [
            entity for entity in network.entities
            if not wanted or entity.id in wanted
        ][:max_entities]
        if not entities:
            return "暂无幕后实体档案。若剧情需要新出场主体，请提出结构化实体与关系提议。"

        selected = {entity.id for entity in entities}
        lines = ["【幕后实体与关系网（仅供规划，禁止按此向读者直接泄露）】"]
        for entity in entities:
            arc = entity.arc.current or entity.arc.destination
            volume_role = entity.volume_roles.get(str(volume_number), "") if volume_number else ""
            details = [
                f"身份/职责：{entity.story_role or entity.kind}",
                f"表层目标：{entity.surface_goal or '待定'}",
                f"内在需求/恐惧：{entity.inner_need or '待定'} / {entity.fear or '待定'}",
                f"缺陷：{entity.flaw or '待定'}",
            ]
            if arc:
                details.append(f"弧线：{arc}")
            if volume_role:
                details.append(f"本卷职责：{volume_role}")
            lines.append(f"- {entity.id}（{entity.name}）：{'；'.join(details)}")

        for relation in network.relationships:
            if relation.source_entity_id not in selected or relation.target_entity_id not in selected:
                continue
            tension = relation.conflict or relation.stakes or relation.status
            lines.append(
                f"- 关系 {relation.source_entity_id} → {relation.target_entity_id}"
                f"（{relation.relationship_type}）：{tension or '待定'}"
            )
        return "\n".join(lines)

    @staticmethod
    def _new_entity(proposal: PlanningEntityProposal, source: str) -> PlanningEntity:
        fields = proposal.model_dump(exclude_none=True)
        fields.pop("id", None)
        name = fields.pop("name", None) or proposal.id
        return PlanningEntity(
            id=proposal.id,
            name=name,
            source=source,
            **fields,
        )

    @staticmethod
    def _new_relationship(
        proposal: RelationshipProposal, source: str
    ) -> EntityRelationship | None:
        if not proposal.source_entity_id or not proposal.target_entity_id:
            return None
        fields = proposal.model_dump(exclude_none=True)
        fields.pop("id", None)
        return EntityRelationship(id=proposal.id, source=source, **fields)

    @staticmethod
    def _relationship_endpoints_exist(
        relationship: EntityRelationship, entities: dict[str, PlanningEntity]
    ) -> bool:
        return (
            relationship.source_entity_id in entities
            and relationship.target_entity_id in entities
        )

    @staticmethod
    def _merge_entity(
        entity: PlanningEntity,
        proposal: PlanningEntityProposal,
        result: ReconcileResult,
    ) -> bool:
        changed = False
        for field_name, value in proposal.model_dump(exclude_none=True).items():
            if field_name == "id":
                continue
            if entity.is_locked(field_name):
                result.skipped_locked_fields.append(f"entity:{entity.id}.{field_name}")
                continue
            if field_name == "volume_roles":
                value = {**entity.volume_roles, **value}
            if getattr(entity, field_name) != value:
                setattr(entity, field_name, value)
                changed = True
        return changed

    @staticmethod
    def _merge_relationship(
        relationship: EntityRelationship,
        proposal: RelationshipProposal,
        result: ReconcileResult,
    ) -> bool:
        changed = False
        for field_name, value in proposal.model_dump(exclude_none=True).items():
            if field_name == "id":
                continue
            if relationship.is_locked(field_name):
                result.skipped_locked_fields.append(
                    f"relationship:{relationship.id}.{field_name}"
                )
                continue
            if getattr(relationship, field_name) != value:
                setattr(relationship, field_name, value)
                changed = True
        return changed
