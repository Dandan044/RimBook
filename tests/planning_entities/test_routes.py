from __future__ import annotations

from types import SimpleNamespace

from rimbook.planning_entities import (
    EntityNetworkService,
    EntityRelationship,
    PlanningEntity,
    PlanningEntityStore,
)
from rimbook.project import scaffold_project
from rimbook.web.backend.routes.planning_entities import (
    FieldLockIn,
    SyncIn,
    create_entity,
    create_relationship,
    delete_entity,
    get_network,
    set_field_lock,
    sync_network,
)


def _deps(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    service = EntityNetworkService(PlanningEntityStore(paths))

    class Planner:
        def sync_planning_entities(self, *, volume=None):
            return {"change_count": 1, "volume": volume}

    return SimpleNamespace(planning_entities=service, planner=Planner())


def test_routes_manage_entity_relationship_locks_and_sync(tmp_path):
    deps = _deps(tmp_path)
    hero = create_entity(PlanningEntity(id="hero", name="林默"), deps)
    mentor = create_entity(PlanningEntity(id="mentor", name="周岚"), deps)
    relationship = create_relationship(
        EntityRelationship(
            id="hero-mentor",
            source_entity_id=hero.id,
            target_entity_id=mentor.id,
            relationship_type="allies",
        ),
        deps,
    )

    assert relationship.id == "hero-mentor"
    assert set_field_lock("hero", FieldLockIn(item_type="entity", field_name="secret", locked=True), deps) == {"ok": True}
    locked = next(e for e in get_network(deps).entities if e.id == "hero")
    assert locked.field_locks == ["secret"]
    assert sync_network(SyncIn(volume=2), deps) == {"change_count": 1, "volume": 2}
    assert delete_entity("hero", deps) == {"ok": True}
    assert get_network(deps).relationships == []
