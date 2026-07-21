"""Author-side planning entity and relationship network routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from rimbook.planning_entities import EntityNetwork, EntityRelationship, PlanningEntity

from ..deps import ProjectDeps, get_project_deps

router = APIRouter(
    prefix="/api/projects/{project_id}/planning-entities",
    tags=["planning-entities"],
)


class FieldLockIn(BaseModel):
    item_type: str
    field_name: str
    locked: bool


class SyncIn(BaseModel):
    volume: int | None = None


@router.get("", response_model=EntityNetwork)
def get_network(deps: ProjectDeps = Depends(get_project_deps)) -> EntityNetwork:
    return deps.planning_entities.store.read_network()


@router.get("/entities", response_model=list[PlanningEntity])
def list_entities(deps: ProjectDeps = Depends(get_project_deps)) -> list[PlanningEntity]:
    return deps.planning_entities.store.list_entities()


@router.post("/entities", response_model=PlanningEntity, status_code=201)
def create_entity(
    entity: PlanningEntity, deps: ProjectDeps = Depends(get_project_deps)
) -> PlanningEntity:
    try:
        deps.planning_entities.store.get_entity(entity.id)
    except FileNotFoundError:
        return deps.planning_entities.store.save_entity(entity)
    raise HTTPException(409, f"规划实体 {entity.id!r} 已存在")


@router.get("/entities/{entity_id}", response_model=PlanningEntity)
def get_entity(
    entity_id: str, deps: ProjectDeps = Depends(get_project_deps)
) -> PlanningEntity:
    try:
        return deps.planning_entities.store.get_entity(entity_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/entities/{entity_id}", response_model=PlanningEntity)
def update_entity(
    entity_id: str,
    entity: PlanningEntity,
    deps: ProjectDeps = Depends(get_project_deps),
) -> PlanningEntity:
    if entity.id != entity_id:
        raise HTTPException(400, "路径中的实体 ID 不能修改")
    try:
        deps.planning_entities.store.get_entity(entity_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return deps.planning_entities.store.save_entity(entity)


@router.delete("/entities/{entity_id}")
def delete_entity(
    entity_id: str, deps: ProjectDeps = Depends(get_project_deps)
) -> dict[str, bool]:
    if not deps.planning_entities.store.delete_entity(entity_id):
        raise HTTPException(404, f"规划实体 {entity_id!r} 不存在")
    return {"ok": True}


@router.get("/relationships", response_model=list[EntityRelationship])
def list_relationships(
    deps: ProjectDeps = Depends(get_project_deps),
) -> list[EntityRelationship]:
    return deps.planning_entities.store.list_relationships()


@router.post("/relationships", response_model=EntityRelationship, status_code=201)
def create_relationship(
    relationship: EntityRelationship,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EntityRelationship:
    try:
        deps.planning_entities.store.get_relationship(relationship.id)
    except FileNotFoundError:
        try:
            return deps.planning_entities.store.save_relationship(relationship)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    raise HTTPException(409, f"实体关系 {relationship.id!r} 已存在")


@router.put("/relationships/{relationship_id}", response_model=EntityRelationship)
def update_relationship(
    relationship_id: str,
    relationship: EntityRelationship,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EntityRelationship:
    if relationship.id != relationship_id:
        raise HTTPException(400, "路径中的关系 ID 不能修改")
    try:
        deps.planning_entities.store.get_relationship(relationship_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        return deps.planning_entities.store.save_relationship(relationship)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/relationships/{relationship_id}")
def delete_relationship(
    relationship_id: str, deps: ProjectDeps = Depends(get_project_deps)
) -> dict[str, bool]:
    if not deps.planning_entities.store.delete_relationship(relationship_id):
        raise HTTPException(404, f"实体关系 {relationship_id!r} 不存在")
    return {"ok": True}


@router.put("/locks/{item_id}")
def set_field_lock(
    item_id: str,
    req: FieldLockIn,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict[str, bool]:
    if req.item_type not in {"entity", "relationship"}:
        raise HTTPException(400, "item_type 必须是 entity 或 relationship")
    try:
        deps.planning_entities.store.set_field_lock(
            req.item_type, item_id, req.field_name, req.locked
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@router.post("/sync")
def sync_network(
    req: SyncIn,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict[str, object]:
    return deps.planner.sync_planning_entities(volume=req.volume)
