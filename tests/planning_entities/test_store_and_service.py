from __future__ import annotations

import pytest

from rimbook.planning_entities import (
    EntityNetworkChanges,
    EntityNetworkService,
    EntityRelationship,
    PlanningEntity,
    PlanningEntityProposal,
    PlanningEntityStore,
    PlanningCodexEntry,
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
    assert store.file_for("character", "mentor").exists()


def test_relationship_requires_existing_entity_references(tmp_path):
    store, _ = _service(tmp_path)
    store.save_entity(PlanningEntity(id="hero", name="主角"))

    with pytest.raises(ValueError, match="不存在的条目"):
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


def test_old_state_fields_are_read_but_not_written_back(tmp_path):
    store, _ = _service(tmp_path)
    path = store.file_for("location", "loc_old")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "id: loc_old\n"
        "name: 旧城\n"
        "type: location\n"
        "current_state: 封锁中\n"
        "future_state: 将被摧毁\n"
        "reveal_strategy: 由远行者第一次提到\n"
        "---\n"
        "一座已有百年历史的城市。\n",
        encoding="utf-8",
    )

    entry = store.get_entry("loc_old")
    assert "current_state" not in entry.model_dump()
    assert "future_state" not in entry.model_dump()
    assert entry.detail == "一座已有百年历史的城市。"
    store.save_entry(entry)
    rewritten = path.read_text(encoding="utf-8")
    assert "current_state" not in rewritten
    assert "future_state" not in rewritten


def test_detail_generation_respects_detail_and_nested_locks(tmp_path):
    store, service = _service(tmp_path)
    store.save_entry(PlanningCodexEntry(
        id="hero",
        name="林默",
        type="character",
        detail="作者手写传记",
        details={"fear": "害怕重蹈父亲覆辙"},
        field_locks=["detail", "fear"],
    ))

    result = service.apply_detail(
        "hero",
        detail="AI 生成传记",
        details_patch={"fear": "害怕失败", "voice": "短句、克制"},
    )
    entry = store.get_entry("hero")
    assert entry.detail == "作者手写传记"
    assert entry.details["fear"] == "害怕重蹈父亲覆辙"
    assert entry.details["voice"] == "短句、克制"
    assert "entity:hero.detail" in result.skipped_locked_fields
    assert "entity:hero.fear" in result.skipped_locked_fields
