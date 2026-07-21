"""YAML-backed persistence for the private author planning entity network."""

from __future__ import annotations

from datetime import datetime, timezone

import yaml

from ..project import ProjectPaths
from ..versioning import atomic_write
from .models import EntityNetwork, EntityRelationship, PlanningEntity

__all__ = ["PlanningEntityStore"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlanningEntityStore:
    """CRUD store for ``planning/entities.yaml``.

    The whole network is intentionally persisted as one human-editable YAML
    document. Relationships are validated against the entity list at write time.
    """

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def read_network(self) -> EntityNetwork:
        path = self.paths.planning_entities_file
        if not path.exists():
            return EntityNetwork()
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return EntityNetwork(**raw) if isinstance(raw, dict) else EntityNetwork()

    def write_network(self, network: EntityNetwork) -> None:
        self._validate_network(network)
        network.updated_at = _now()
        payload = network.model_dump(mode="json")
        atomic_write(
            self.paths.planning_entities_file,
            yaml.dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
        )

    def list_entities(self) -> list[PlanningEntity]:
        return self.read_network().entities

    def get_entity(self, entity_id: str) -> PlanningEntity:
        for entity in self.list_entities():
            if entity.id == entity_id:
                return entity
        raise FileNotFoundError(f"规划实体 {entity_id!r} 不存在")

    def save_entity(self, entity: PlanningEntity) -> PlanningEntity:
        network = self.read_network()
        entity.updated_at = _now()
        for index, existing in enumerate(network.entities):
            if existing.id == entity.id:
                network.entities[index] = entity
                break
        else:
            network.entities.append(entity)
        self.write_network(network)
        return entity

    def delete_entity(self, entity_id: str) -> bool:
        network = self.read_network()
        remaining = [entity for entity in network.entities if entity.id != entity_id]
        if len(remaining) == len(network.entities):
            return False
        network.entities = remaining
        network.relationships = [
            relation
            for relation in network.relationships
            if relation.source_entity_id != entity_id and relation.target_entity_id != entity_id
        ]
        self.write_network(network)
        return True

    def list_relationships(self) -> list[EntityRelationship]:
        return self.read_network().relationships

    def get_relationship(self, relationship_id: str) -> EntityRelationship:
        for relationship in self.list_relationships():
            if relationship.id == relationship_id:
                return relationship
        raise FileNotFoundError(f"实体关系 {relationship_id!r} 不存在")

    def save_relationship(self, relationship: EntityRelationship) -> EntityRelationship:
        network = self.read_network()
        known_ids = {entity.id for entity in network.entities}
        missing = {
            entity_id
            for entity_id in (relationship.source_entity_id, relationship.target_entity_id)
            if entity_id not in known_ids
        }
        if missing:
            raise ValueError(f"关系引用了不存在的实体: {', '.join(sorted(missing))}")
        relationship.updated_at = _now()
        for index, existing in enumerate(network.relationships):
            if existing.id == relationship.id:
                network.relationships[index] = relationship
                break
        else:
            network.relationships.append(relationship)
        self.write_network(network)
        return relationship

    def delete_relationship(self, relationship_id: str) -> bool:
        network = self.read_network()
        remaining = [relation for relation in network.relationships if relation.id != relationship_id]
        if len(remaining) == len(network.relationships):
            return False
        network.relationships = remaining
        self.write_network(network)
        return True

    def set_field_lock(self, item_type: str, item_id: str, field_name: str, locked: bool) -> None:
        """Lock or unlock one direct field on an entity or relationship."""
        network = self.read_network()
        collection = network.entities if item_type == "entity" else network.relationships
        for item in collection:
            if item.id != item_id:
                continue
            if field_name not in item.field_locks and locked:
                item.field_locks.append(field_name)
            elif field_name in item.field_locks and not locked:
                item.field_locks.remove(field_name)
            item.updated_at = _now()
            self.write_network(network)
            return
        kind = "规划实体" if item_type == "entity" else "实体关系"
        raise FileNotFoundError(f"{kind} {item_id!r} 不存在")

    @staticmethod
    def _validate_network(network: EntityNetwork) -> None:
        entity_ids = [entity.id for entity in network.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("规划实体 ID 不能重复")
        relationship_ids = [relationship.id for relationship in network.relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("实体关系 ID 不能重复")
        known_ids = set(entity_ids)
        for relationship in network.relationships:
            if relationship.source_entity_id not in known_ids or relationship.target_entity_id not in known_ids:
                raise ValueError(f"关系 {relationship.id!r} 引用了不存在的实体")
