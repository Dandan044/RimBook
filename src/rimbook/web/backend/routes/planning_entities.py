"""Author-side planning codex and relationship network routes."""

from __future__ import annotations

import asyncio
import threading
from queue import Empty

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from rimbook.planning_entities import (
    EntityNetwork,
    PlanningCodexEntry,
    PlanningEntity,
    PlanningRelationship,
)

from ..deps import ProjectDeps, get_project_deps
from ..sse import sse_done, sse_event, sse_progress
from ..tasks import task_registry

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


class DetailGenerateIn(BaseModel):
    only_missing: bool = True


class WorldExpandIn(BaseModel):
    coefficient: int = Field(default=2, ge=2, le=4)
    seed_ids: list[str] = Field(default_factory=list)


class GraphLayoutIn(BaseModel):
    nodes: dict[str, dict[str, float]] = Field(default_factory=dict)
    viewport: dict[str, float] = Field(default_factory=dict)


@router.get("", response_model=EntityNetwork)
def get_network(deps: ProjectDeps = Depends(get_project_deps)) -> EntityNetwork:
    return deps.planning_entities.store.read_network()


@router.get("/graph")
def get_graph(
    types: str = "",
    focus: str | None = None,
    depth: int = Query(default=1, ge=0, le=3),
    include_implicit_world: bool = False,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict[str, list[dict]]:
    entry_types = [item.strip() for item in types.split(",") if item.strip()]
    return deps.planning_entities.build_graph(
        entry_types=entry_types or None,
        focus=focus,
        depth=depth,
        include_implicit_world=include_implicit_world,
    )


@router.get("/graph-layout")
def get_graph_layout(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    return deps.planning_entities.store.read_graph_layout()


@router.put("/graph-layout")
def save_graph_layout(
    req: GraphLayoutIn,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict[str, bool]:
    deps.planning_entities.store.write_graph_layout(req.model_dump())
    return {"ok": True}


@router.get("/entries", response_model=list[PlanningCodexEntry])
def list_entries(
    entry_type: str | None = Query(default=None, alias="type"),
    deps: ProjectDeps = Depends(get_project_deps),
) -> list[PlanningCodexEntry]:
    return deps.planning_entities.store.list_entries(entry_type)


@router.post("/entries", response_model=PlanningCodexEntry, status_code=201)
def create_entry(
    entry: PlanningCodexEntry, deps: ProjectDeps = Depends(get_project_deps)
) -> PlanningCodexEntry:
    try:
        deps.planning_entities.store.get_entry(entry.id)
    except FileNotFoundError:
        return deps.planning_entities.store.save_entry(entry)
    raise HTTPException(409, f"规划设定条目 {entry.id!r} 已存在")


@router.get("/entries/{entry_id}", response_model=PlanningCodexEntry)
def get_entry(
    entry_id: str, deps: ProjectDeps = Depends(get_project_deps)
) -> PlanningCodexEntry:
    try:
        return deps.planning_entities.store.get_entry(entry_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/entries/{entry_id}", response_model=PlanningCodexEntry)
def update_entry(
    entry_id: str,
    entry: PlanningCodexEntry,
    deps: ProjectDeps = Depends(get_project_deps),
) -> PlanningCodexEntry:
    if entry.id != entry_id:
        raise HTTPException(400, "路径中的条目 ID 不能修改")
    try:
        deps.planning_entities.store.get_entry(entry_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return deps.planning_entities.store.save_entry(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(
    entry_id: str, deps: ProjectDeps = Depends(get_project_deps)
) -> dict[str, bool]:
    if not deps.planning_entities.store.delete_entry(entry_id):
        raise HTTPException(404, f"规划设定条目 {entry_id!r} 不存在")
    return {"ok": True}


@router.post("/entries/{entry_id}/detail")
def regenerate_entry_detail(
    project_id: str,
    entry_id: str,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EventSourceResponse:
    """Regenerate one entry's detail, even when it already has content."""
    try:
        deps.planning_entities.store.get_entry(entry_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _detail_generation_sse(
        project_id,
        deps,
        entry_ids=[entry_id],
        only_missing=False,
    )


@router.post("/details")
def generate_missing_details(
    project_id: str,
    req: DetailGenerateIn,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EventSourceResponse:
    """Generate all missing details in macro-to-micro order."""
    return _detail_generation_sse(
        project_id,
        deps,
        entry_ids=None,
        only_missing=req.only_missing,
    )


@router.post("/expand")
def expand_world(
    project_id: str,
    req: WorldExpandIn,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EventSourceResponse:
    """Continue expanding the existing full codex under a new hard budget."""
    return _planner_generator_sse(
        project_id,
        deps,
        op="world_expand",
        progress="正在扩展真实世界…",
        generator=lambda: deps.planner.expand_world(
            coefficient=req.coefficient,
            seed_ids=req.seed_ids or None,
        ),
    )


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


@router.get("/relationships", response_model=list[PlanningRelationship])
def list_relationships(
    deps: ProjectDeps = Depends(get_project_deps),
) -> list[PlanningRelationship]:
    return deps.planning_entities.store.list_relationships()


@router.post("/relationships", response_model=PlanningRelationship, status_code=201)
def create_relationship(
    relationship: PlanningRelationship,
    deps: ProjectDeps = Depends(get_project_deps),
) -> PlanningRelationship:
    try:
        deps.planning_entities.store.get_relationship(relationship.id)
    except FileNotFoundError:
        try:
            return deps.planning_entities.store.save_relationship(relationship)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    raise HTTPException(409, f"实体关系 {relationship.id!r} 已存在")


@router.put("/relationships/{relationship_id}", response_model=PlanningRelationship)
def update_relationship(
    relationship_id: str,
    relationship: PlanningRelationship,
    deps: ProjectDeps = Depends(get_project_deps),
) -> PlanningRelationship:
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
    if req.item_type not in {"entity", "entry", "relationship"}:
        raise HTTPException(400, "item_type 必须是 entity、entry 或 relationship")
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


def _detail_generation_sse(
    project_id: str,
    deps: ProjectDeps,
    *,
    entry_ids: list[str] | None,
    only_missing: bool,
) -> EventSourceResponse:
    op = "codex_detail"
    started = task_registry.try_start(
        project_id,
        op,
        None,
        "正在细化完整设定集详情…",
    )

    if started:
        def _run() -> None:
            try:
                for event in deps.planner.generate_codex_details(
                    entry_ids=entry_ids,
                    only_missing=only_missing,
                ):
                    kind = event["event"]
                    data = event["data"]
                    message = data.get("message", "") if isinstance(data, dict) else ""
                    if message:
                        task_registry.update(project_id, op, message, None)
                    if kind != "progress":
                        # update() already fans progress out to subscribers.
                        task_registry.publish(project_id, op, None, kind, data)
                payload = {"entry_ids": entry_ids or [], "only_missing": only_missing}
                task_registry.publish(project_id, op, None, "done", payload)
                task_registry.mark_finished(project_id, op, None)
            except Exception as exc:  # noqa: BLE001
                task_registry.publish(
                    project_id, op, None, "error", {"message": str(exc)}
                )
                task_registry.mark_finished(project_id, op, None, error=str(exc))

        threading.Thread(
            target=_run,
            name=f"codex-detail-{project_id}",
            daemon=True,
        ).start()

    async def event_stream():
        sub = task_registry.subscribe(project_id, op, None)
        if sub is None:
            yield sse_event("error", {"message": "无法订阅详情生成任务"})
            yield sse_done()
            return
        event_q, _, snapshot_progress, already_finished = sub
        if snapshot_progress:
            yield sse_progress(snapshot_progress)
        if already_finished:
            task = task_registry.get(project_id, op, None)
            if task is not None and task.error:
                yield sse_event("error", {"message": task.error})
            yield sse_done()
            return
        try:
            while True:
                try:
                    kind, payload = await asyncio.to_thread(
                        event_q.get, True, 0.25
                    )
                except Empty:
                    task = task_registry.get(project_id, op, None)
                    if task is None or task.finished:
                        yield sse_done()
                        return
                    continue
                if kind == "__end__":
                    yield sse_done()
                    return
                if kind == "step":
                    yield sse_event("step", payload)
                elif kind == "progress":
                    message = (
                        payload.get("message", "")
                        if isinstance(payload, dict)
                        else str(payload)
                    )
                    yield sse_progress(message)
                elif kind == "error":
                    yield sse_event("error", payload)
                    yield sse_done()
                    return
                elif kind == "done":
                    yield sse_done(payload if isinstance(payload, dict) else {})
                    return
        finally:
            task_registry.unsubscribe(project_id, op, None, event_q)

    return EventSourceResponse(event_stream(), ping=10)


def _planner_generator_sse(
    project_id: str,
    deps: ProjectDeps,
    *,
    op: str,
    progress: str,
    generator,
) -> EventSourceResponse:
    started = task_registry.try_start(project_id, op, None, progress)
    if started:
        def _run() -> None:
            try:
                for event in generator():
                    kind = event["event"]
                    data = event["data"]
                    message = data.get("message", "") if isinstance(data, dict) else ""
                    if message:
                        task_registry.update(project_id, op, message, None)
                    if kind != "progress":
                        task_registry.publish(project_id, op, None, kind, data)
                task_registry.publish(project_id, op, None, "done", {})
                task_registry.mark_finished(project_id, op, None)
            except Exception as exc:  # noqa: BLE001
                task_registry.publish(
                    project_id, op, None, "error", {"message": str(exc)}
                )
                task_registry.mark_finished(project_id, op, None, error=str(exc))

        threading.Thread(
            target=_run,
            name=f"{op}-{project_id}",
            daemon=True,
        ).start()

    async def event_stream():
        sub = task_registry.subscribe(project_id, op, None)
        if sub is None:
            yield sse_event("error", {"message": "无法订阅世界扩展任务"})
            yield sse_done()
            return
        event_q, _, snapshot_progress, already_finished = sub
        if snapshot_progress:
            yield sse_progress(snapshot_progress)
        if already_finished:
            task = task_registry.get(project_id, op, None)
            if task is not None and task.error:
                yield sse_event("error", {"message": task.error})
            yield sse_done()
            return
        try:
            while True:
                try:
                    kind, payload = await asyncio.to_thread(
                        event_q.get, True, 0.25
                    )
                except Empty:
                    task = task_registry.get(project_id, op, None)
                    if task is None or task.finished:
                        yield sse_done()
                        return
                    continue
                if kind == "__end__":
                    yield sse_done()
                    return
                if kind == "step":
                    yield sse_event("step", payload)
                elif kind == "progress":
                    message = payload.get("message", "") if isinstance(payload, dict) else str(payload)
                    yield sse_progress(message)
                elif kind == "error":
                    yield sse_event("error", payload)
                    yield sse_done()
                    return
                elif kind == "done":
                    yield sse_done(payload if isinstance(payload, dict) else {})
                    return
        finally:
            task_registry.unsubscribe(project_id, op, None, event_q)

    return EventSourceResponse(event_stream(), ping=10)
