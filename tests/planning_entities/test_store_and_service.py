from __future__ import annotations

import pytest

from rimbook.planning_entities import (
    EntityNetworkChanges,
    EntityNetworkService,
    EntityRelationship,
    PlanningEntity,
    PlanningEntityProposal,
    PlanningEntityStore,
    RelationshipProposal,
)
from rimbook.project import scaffold_project


def _service(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    store = PlanningEntityStore(paths)
    return store, EntityNetworkService(store)


def test_store_round_trips_and_deletes_linked_relationships(tmp_path):
    store, _ = _service(tmp_path)
    store.save_entity(PlanningEntity(id="hero", name="主角"))
    store.save_entity(PlanningEntity(id="mentor", name="导师"))
    store.save_relationship(
        EntityRelationship(
            id="hero-mentor",
            source_entity_id="hero",
            target_entity_id="mentor",
            relationship_type="student_of",
        )
    )

    network = store.read_network()
    assert [entity.id for entity in network.entities] == ["hero", "mentor"]
    assert network.relationships[0].relationship_type == "student_of"
    assert store.delete_entity("hero") is True
    assert store.list_relationships() == []
    assert store.paths.planning_entities_file.exists()


def test_relationship_requires_existing_entity_references(tmp_path):
    store, _ = _service(tmp_path)
    store.save_entity(PlanningEntity(id="hero", name="主角"))

    with pytest.raises(ValueError, match="不存在的实体"):
        store.save_relationship(
            EntityRelationship(
                id="hero-ghost",
                source_entity_id="hero",
                target_entity_id="ghost",
            )
        )


def test_reconcile_respects_locks_and_is_idempotent(tmp_path):
    store, service = _service(tmp_path)
    store.save_entity(
        PlanningEntity(
            id="hero",
            name="林默",
            surface_goal="查清旧案",
            field_locks=["surface_goal"],
        )
    )

    changes = EntityNetworkChanges(
        entities=[
            PlanningEntityProposal(
                id="hero",
                name="林默",
                surface_goal="夺回家族产业",
                inner_need="证明自己值得被爱",
            ),
            PlanningEntityProposal(id="mentor", name="周岚", story_role="引路人"),
        ],
        relationships=[
            RelationshipProposal(
                id="hero-mentor",
                source_entity_id="hero",
                target_entity_id="mentor",
                relationship_type="allies",
                conflict="互相隐瞒关键证据",
            )
        ],
    )

    result = service.reconcile(changes, source="volume_plan")
    hero = store.get_entity("hero")
    assert hero.surface_goal == "查清旧案"
    assert hero.inner_need == "证明自己值得被爱"
    assert result.created_entities == ["mentor"]
    assert result.created_relationships == ["hero-mentor"]
    assert "entity:hero.surface_goal" in result.skipped_locked_fields

    repeat = service.reconcile(changes, source="volume_plan")
    assert repeat.change_count == 0


def test_render_brief_limits_to_requested_entities_and_relationships(tmp_path):
    store, service = _service(tmp_path)
    service.reconcile(
        EntityNetworkChanges(
            entities=[
                PlanningEntityProposal(id="hero", name="林默", surface_goal="查案"),
                PlanningEntityProposal(id="mentor", name="周岚", fear="真相曝光"),
                PlanningEntityProposal(id="outsider", name="外来者"),
            ],
            relationships=[
                RelationshipProposal(
                    id="hero-mentor",
                    source_entity_id="hero",
                    target_entity_id="mentor",
                    conflict="证据归属",
                )
            ],
        ),
        source="story_backfill",
    )

    brief = service.render_brief(["hero", "mentor"])
    assert "林默" in brief
    assert "周岚" in brief
    assert "外来者" not in brief
    assert "证据归属" in brief


def test_malformed_optional_llm_changes_are_ignored():
    changes = EntityNetworkChanges.from_payload({
        "entities": [
            "主角：本卷开始怀疑同伴",
            {"id": "hero", "surface_goal": "查清旧案"},
            {"name": "缺少稳定 ID"},
        ],
        "relationships": [
            "主角→同伴：信任破裂",
            {"id": "hero-mentor", "source_entity_id": "hero", "target_entity_id": "mentor"},
        ],
    })

    assert [item.id for item in changes.entities] == ["hero"]
    assert [item.id for item in changes.relationships] == ["hero-mentor"]
