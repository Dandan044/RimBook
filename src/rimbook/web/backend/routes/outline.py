"""Outline management routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from rimbook.outline import ChapterOutline, SceneBeat, VolumeOutline, RawBeat, VolumeBeatData, MicroScene

from ..deps import ProjectDeps, get_project_deps
from ..sse import sse_done, sse_event, sse_progress
from ..tasks import task_registry

router = APIRouter(prefix="/api/projects/{project_id}/outline", tags=["outline"])


# ---- models ----

class MicroSceneIn(BaseModel):
    intent: str = ""
    sensory: str = ""
    action: str = ""
    dialogue: str = ""
    event: str = ""
    technique: str = ""
    pacing: str = ""
    words: int = 0


class MicroSceneOut(BaseModel):
    intent: str = ""
    sensory: str = ""
    action: str = ""
    dialogue: str = ""
    event: str = ""
    technique: str = ""
    pacing: str = ""
    words: int = 0


class SceneBeatIn(BaseModel):
    goal: str = ""
    conflict: str = ""
    outcome: str = ""
    entities: list[str] = []
    scenes: list[MicroSceneIn] = []


class SceneBeatOut(BaseModel):
    goal: str
    conflict: str
    outcome: str
    entities: list[str]
    scenes: list[MicroSceneOut] = []


class ChapterOutlineIn(BaseModel):
    title: str = ""
    volume: int | None = None
    entities: list[str] = []
    tags: list[str] = []
    beats: list[SceneBeatIn] = []
    notes: str = ""
    keynote: list[str] = []
    purpose: str = ""
    value_shift: str = ""
    tension: int = 0
    hook: str = ""
    story_date: str = ""
    elapsed: str = ""


class ChapterOutlineOut(BaseModel):
    number: int
    title: str
    volume: int | None
    entities: list[str]
    tags: list[str]
    beats: list[SceneBeatOut]
    notes: str
    keynote: list[str] = []
    summary: str
    purpose: str = ""
    value_shift: str = ""
    tension: int = 0
    hook: str = ""
    story_date: str = ""
    elapsed: str = ""
    has_draft: bool = False


class VolumeOutlineIn(BaseModel):
    title: str = ""
    arc: str = ""
    chapters: list[int] = []
    ending: str = ""


class VolumeOutlineOut(BaseModel):
    number: int
    title: str
    arc: str
    chapters: list[int]
    recap: str = ""
    ending: str


class SynopsisIn(BaseModel):
    text: str


class FoundationIn(SynopsisIn):
    expansion_coefficient: int | None = Field(default=None, ge=1, le=4)


class PlanChapterRequest(BaseModel):
    volume: int | None = None
    title: str = ""
    hint: str = ""


# ---- synopsis ----

@router.get("/synopsis")
def get_synopsis(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    text = deps.outline.read_synopsis()
    return {"text": text}


@router.put("/synopsis")
def update_synopsis(req: SynopsisIn, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    deps.outline.write_synopsis(req.text)
    return {"ok": True}


@router.post("/synopsis")
def generate_synopsis(req: SynopsisIn, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """LLM-generate macro synopsis from a premise (sync compat). req.text = premise."""
    text = deps.planner.plan_synopsis(req.text)
    return {"text": text}


@router.post("/foundation")
def generate_foundation_sse(
    project_id: str,
    req: FoundationIn,
    resume: bool = False,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EventSourceResponse:
    """Foundation SSE: synopsis, rough codex, detail layers; reconnectable."""
    if resume:
        active = task_registry.get(project_id, "foundation", None)
        if active is None or active.finished:
            async def no_job():
                yield sse_event("error", {"message": "没有进行中的基础设定任务"})
                yield sse_done()
            return EventSourceResponse(no_job(), ping=10)
        return _foundation_pipeline_sse(project_id)

    coefficient = (
        req.expansion_coefficient
        if req.expansion_coefficient is not None
        else deps.config.world_expansion.coefficient
    )
    started = task_registry.try_start(
        project_id, "foundation", None, "正在生成项目基础设定…"
    )
    if started:
        _spawn_foundation_worker(project_id, req.text, coefficient, deps)
    return _foundation_pipeline_sse(project_id)


def _spawn_foundation_worker(
    project_id: str,
    premise: str,
    coefficient: int,
    deps: ProjectDeps,
) -> None:
    import json
    import threading
    import time

    def _run() -> None:
        try:
            task_registry.update(
                project_id, "foundation", "正在生成项目基础设定…", None,
            )
            # Seed snapshot so resume clients know expansion coefficient early.
            task_registry.set_stream(
                project_id,
                "foundation",
                None,
                json.dumps(
                    {
                        "step": 0,
                        "status": "running",
                        "message": "正在生成项目基础设定…",
                        "expansion_coefficient": coefficient,
                    },
                    ensure_ascii=False,
                ),
            )
            for event in deps.planner.plan_foundation(
                premise,
                expansion_coefficient=coefficient,
            ):
                kind = event["event"]
                data = event["data"]
                if kind == "step":
                    msg = data.get("message") or f"Step {data.get('step')}"
                    task_registry.update(project_id, "foundation", msg, None)
                    # Snapshot for reconnect (omit bulky reconcile payload).
                    snap = {k: v for k, v in data.items() if k != "changes"}
                    snap["expansion_coefficient"] = coefficient
                    if not snap.get("message"):
                        step_n = snap.get("step")
                        status = snap.get("status")
                        if status == "running":
                            snap["message"] = f"步骤 {step_n} 进行中…"
                        elif status == "done":
                            snap["message"] = f"步骤 {step_n} 完成"
                    task_registry.set_stream(
                        project_id,
                        "foundation",
                        None,
                        json.dumps(snap, ensure_ascii=False),
                    )
                    task_registry.publish(
                        project_id, "foundation", None, kind, data,
                    )
                elif kind == "progress":
                    msg = data.get("message", "") if isinstance(data, dict) else str(data)
                    if msg:
                        # update() already fans out progress — don't double-publish.
                        task_registry.update(project_id, "foundation", msg, None)
                else:
                    task_registry.publish(
                        project_id, "foundation", None, kind, data,
                    )
            task_registry.publish(project_id, "foundation", None, "done", {})
            task_registry.mark_finished(project_id, "foundation", None)
        except Exception as exc:  # noqa: BLE001
            task_registry.publish(
                project_id, "foundation", None, "error", {"message": str(exc)},
            )
            task_registry.mark_finished(
                project_id, "foundation", None, error=str(exc),
            )
        finally:
            def _cleanup() -> None:
                time.sleep(120)
                t = task_registry.get(project_id, "foundation", None)
                if t is not None and t.finished:
                    task_registry.unregister(project_id, "foundation", None)

            threading.Thread(
                target=_cleanup,
                name=f"foundation-cleanup-{project_id}",
                daemon=True,
            ).start()

    threading.Thread(
        target=_run,
        name=f"foundation-{project_id}",
        daemon=True,
    ).start()


def _foundation_pipeline_sse(project_id: str) -> EventSourceResponse:
    """Attach SSE subscriber to an in-flight foundation job."""
    from queue import Empty
    import json

    sub = task_registry.subscribe(project_id, "foundation", None)
    if sub is None:
        async def no_job():
            yield sse_event("error", {"message": "无法订阅基础设定任务"})
            yield sse_done()
        return EventSourceResponse(no_job(), ping=10)

    event_q, snapshot_text, snapshot_progress, already_finished = sub

    async def event_stream():
        try:
            if snapshot_progress:
                yield sse_progress(snapshot_progress)
            if snapshot_text:
                try:
                    snap = json.loads(snapshot_text)
                    yield sse_event("step", snap)
                except (json.JSONDecodeError, TypeError):
                    pass
            if already_finished:
                t = task_registry.get(project_id, "foundation", None)
                if t is not None and t.error:
                    yield sse_event("error", {"message": t.error})
                else:
                    yield sse_done({})
                return

            while True:
                try:
                    kind, payload = await asyncio.to_thread(event_q.get, True, 0.25)
                except Empty:
                    t = task_registry.get(project_id, "foundation", None)
                    if t is None or t.finished:
                        t = task_registry.get(project_id, "foundation", None)
                        if t is not None and t.error:
                            yield sse_event("error", {"message": t.error})
                        yield sse_done({})
                        return
                    continue

                if kind == "__end__":
                    t = task_registry.get(project_id, "foundation", None)
                    if t is not None and t.error:
                        yield sse_event("error", {"message": t.error})
                    yield sse_done({})
                    return

                if kind == "progress":
                    msg = (
                        payload.get("message", "")
                        if isinstance(payload, dict)
                        else str(payload)
                    )
                    yield sse_progress(msg)
                elif kind == "step":
                    yield sse_event("step", payload)
                elif kind == "error":
                    msg = (
                        payload.get("message", str(payload))
                        if isinstance(payload, dict)
                        else str(payload)
                    )
                    yield sse_event("error", {"message": msg})
                    yield sse_done()
                    return
                elif kind == "done":
                    yield sse_done(payload if isinstance(payload, dict) else {})
                    return
        except asyncio.CancelledError:
            return
        finally:
            task_registry.unsubscribe(project_id, "foundation", None, event_q)

    return EventSourceResponse(
        event_stream(),
        ping=10,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/foundation-status")
def foundation_status(project_id: str) -> dict:
    """Return the active (or recently finished) foundation job for this project."""
    import json

    active = task_registry.get(project_id, "foundation", None)
    if active is None:
        return {
            "active": False,
            "finished": False,
            "progress": "",
            "step": None,
            "error": None,
            "expansion_coefficient": None,
            "started_at": None,
        }
    step = None
    expansion_coefficient = None
    if active.stream_text:
        try:
            step = json.loads(active.stream_text)
            if isinstance(step, dict):
                expansion_coefficient = step.get("expansion_coefficient")
        except (json.JSONDecodeError, TypeError):
            step = None
    return {
        "active": not active.finished,
        "finished": active.finished,
        "progress": active.progress,
        "step": step,
        "error": active.error,
        "expansion_coefficient": expansion_coefficient,
        "started_at": active.started_at,
    }


# ---- volumes ----

@router.get("/volumes", response_model=list[VolumeOutlineOut])
def list_volumes(deps: ProjectDeps = Depends(get_project_deps)) -> list[VolumeOutlineOut]:
    vols = deps.outline.list_volumes()
    return [_vol_out(v) for v in vols]


# ---- volume planning (beat chain → refine → assemble) ----

class PlanVolumeV2Request(BaseModel):
    title: str = ""


class RawBeatIn(BaseModel):
    id: str = ""
    goal: str = ""
    conflict: str = ""
    outcome: str = ""
    entities: list[str] = []
    momentum: str = ""


class RawBeatOut(BaseModel):
    id: str
    goal: str
    conflict: str
    outcome: str
    entities: list[str]
    momentum: str


class VolumeBeatDataOut(BaseModel):
    volume: int
    step: int
    raw_beats: list[RawBeatOut]
    refined_beats: list[dict] = []
    chapter_map: list[dict] = []


class BeatUpdateRequest(BaseModel):
    beats: list[RawBeatIn]


class BeatReorderRequest(BaseModel):
    ordered_ids: list[str]


@router.post("/volumes/plan")
def plan_volume_v2_sse(
    project_id: str,
    req: PlanVolumeV2Request,
    resume: bool = False,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EventSourceResponse:
    """Full v2 volume planning pipeline with reconnectable SSE (Step 1+2+3)."""
    from queue import Empty
    import threading
    import time

    existing = deps.outline.list_volumes()
    # When resuming, attach to the newest active plan_volume task if any.
    number: int | None = None
    if resume:
        for t in task_registry.list_for_project(project_id):
            if t.op == "plan_volume" and not t.finished and t.chapter is not None:
                number = t.chapter
                break
        if number is None:
            async def no_job():
                yield sse_event("error", {"message": "没有进行中的卷规划任务"})
                yield sse_done()
            return EventSourceResponse(no_job(), ping=10)
    else:
        number = max((v.number for v in existing), default=0) + 1
        started = task_registry.try_start(
            project_id, "plan_volume", number, f"正在规划第 {number} 卷…",
        )
        if started:
            _spawn_plan_volume_worker(project_id, number, req.title or "", deps)

    assert number is not None
    return _volume_pipeline_sse(project_id, "plan_volume", number)


def _spawn_plan_volume_worker(
    project_id: str, number: int, title: str, deps: ProjectDeps,
) -> None:
    import threading
    import time
    import json

    def _run() -> None:
        try:
            task_registry.update(
                project_id, "plan_volume", f"正在规划第 {number} 卷…", number,
            )
            task_registry.publish(
                project_id, "plan_volume", number, "progress",
                {"message": f"正在规划第 {number} 卷…"},
            )
            for event in deps.planner.plan_volume_v2(number, title=title):
                kind = event["event"]
                data = event["data"]
                if kind == "step":
                    msg = data.get("message") or f"Step {data.get('step')} {data.get('status', '')}"
                    task_registry.update(project_id, "plan_volume", msg, number)
                    # Snapshot for reconnect (omit bulky beats list).
                    snap = {k: v for k, v in data.items() if k != "beats"}
                    if isinstance(snap.get("volume"), dict):
                        snap["volume"] = snap["volume"].get("number", number)
                    else:
                        snap["volume"] = number
                    if "beats" in data:
                        snap["beat_count"] = len(data["beats"])
                    # Ensure UI has a message even on done events.
                    if not snap.get("message"):
                        step_n = snap.get("step")
                        status = snap.get("status")
                        if status == "running":
                            snap["message"] = f"步骤 {step_n} 进行中…"
                        elif status == "done":
                            snap["message"] = f"步骤 {step_n} 完成"
                    task_registry.set_stream(
                        project_id, "plan_volume", number, json.dumps(snap, ensure_ascii=False),
                    )
                    task_registry.publish(project_id, "plan_volume", number, kind, data)
                elif kind == "progress":
                    msg = data.get("message", "") if isinstance(data, dict) else str(data)
                    if msg:
                        # update() already fans out a progress event — don't double-publish.
                        task_registry.update(project_id, "plan_volume", msg, number)
                else:
                    task_registry.publish(project_id, "plan_volume", number, kind, data)

            task_registry.publish(
                project_id, "plan_volume", number, "done", {"volume_number": number},
            )
            task_registry.mark_finished(project_id, "plan_volume", number)
        except Exception as exc:  # noqa: BLE001
            task_registry.publish(project_id, "plan_volume", number, "error", {"message": str(exc)})
            task_registry.mark_finished(project_id, "plan_volume", number, error=str(exc))
        finally:
            def _cleanup() -> None:
                time.sleep(120)
                t = task_registry.get(project_id, "plan_volume", number)
                if t is not None and t.finished:
                    task_registry.unregister(project_id, "plan_volume", number)
            threading.Thread(
                target=_cleanup, name=f"plan-vol-cleanup-{number}", daemon=True,
            ).start()

    threading.Thread(
        target=_run, name=f"plan-volume-{project_id}-{number}", daemon=True,
    ).start()


def _volume_pipeline_sse(
    project_id: str, op: str, number: int,
) -> EventSourceResponse:
    """Attach SSE subscriber to an in-flight plan_volume / assemble_volume job."""
    from queue import Empty
    import json

    sub = task_registry.subscribe(project_id, op, number)
    if sub is None:
        async def no_job():
            yield sse_event("error", {"message": "没有进行中的任务"})
            yield sse_done()
        return EventSourceResponse(no_job(), ping=10)

    event_q, snapshot_text, snapshot_progress, already_finished = sub

    async def event_stream():
        try:
            if snapshot_progress:
                yield sse_progress(snapshot_progress)
            if snapshot_text:
                try:
                    snap = json.loads(snapshot_text)
                    yield sse_event("step", snap)
                except (json.JSONDecodeError, TypeError):
                    pass
            if already_finished:
                t = task_registry.get(project_id, op, number)
                if t is not None and t.error:
                    yield sse_event("error", {"message": t.error})
                else:
                    yield sse_done({"volume_number": number})
                return

            while True:
                try:
                    kind, payload = await asyncio.to_thread(event_q.get, True, 0.25)
                except Empty:
                    t = task_registry.get(project_id, op, number)
                    if t is None or t.finished:
                        t = task_registry.get(project_id, op, number)
                        if t is not None and t.error:
                            yield sse_event("error", {"message": t.error})
                        yield sse_done({"volume_number": number})
                        return
                    continue

                if kind == "__end__":
                    t = task_registry.get(project_id, op, number)
                    if t is not None and t.error:
                        yield sse_event("error", {"message": t.error})
                    yield sse_done({"volume_number": number})
                    return

                if kind == "progress":
                    msg = payload.get("message", "") if isinstance(payload, dict) else str(payload)
                    yield sse_progress(msg)
                elif kind == "step":
                    yield sse_event("step", payload)
                elif kind == "error":
                    msg = payload.get("message", str(payload)) if isinstance(payload, dict) else str(payload)
                    yield sse_event("error", {"message": msg})
                    yield sse_done()
                    return
                elif kind == "done":
                    yield sse_done(payload if isinstance(payload, dict) else {"volume_number": number})
                    return
        except asyncio.CancelledError:
            return
        finally:
            task_registry.unsubscribe(project_id, op, number, event_q)

    return EventSourceResponse(
        event_stream(),
        ping=10,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/volumes/plan-status")
def plan_volume_status(project_id: str) -> dict:
    """Return the active (or recently finished) volume-plan job for this project."""
    import json
    active = None
    for t in task_registry.list_for_project(project_id):
        if t.op in ("plan_volume", "assemble_volume"):
            active = t
            if not t.finished:
                break
    if active is None:
        return {"active": False, "finished": False, "op": "", "volume": None, "progress": "", "step": None, "error": None}
    step = None
    if active.stream_text:
        try:
            step = json.loads(active.stream_text)
        except (json.JSONDecodeError, TypeError):
            step = None
    return {
        "active": not active.finished,
        "finished": active.finished,
        "op": active.op,
        "volume": active.chapter,
        "progress": active.progress,
        "step": step,
        "error": active.error,
        "started_at": active.started_at,
    }


@router.get("/volumes/{number}/beats")
def get_volume_beats(number: int, deps: ProjectDeps = Depends(get_project_deps)):
    """Get the beat pipeline data for a volume."""
    data = deps.outline.load_volume_beats(number)
    if data is None:
        return {"volume": number, "step": 0, "raw_beats": [], "refined_beats": [], "chapter_map": []}
    return VolumeBeatDataOut(
        volume=data.volume,
        step=data.step,
        raw_beats=[RawBeatOut(**b.model_dump()) for b in data.raw_beats],
        refined_beats=[b.model_dump() for b in data.refined_beats],
        chapter_map=[c.model_dump() for c in data.chapter_map],
    )


class FrameworkReaderLensOut(BaseModel):
    current_perspective: str = ""
    what_they_want: str = ""
    reveal_debts: list[str] = []


class FrameworkCraftFocusOut(BaseModel):
    conflict: str = ""
    reversal: str = ""
    development: str = ""
    suspense: str = ""
    other: str = ""


class FrameworkStageOut(BaseModel):
    id: str
    why_this_stage: str = ""
    dramatic_pressure: str = ""


class FrameworkCastOut(BaseModel):
    id: str
    billing: str = "supporting"
    situation: str = ""
    dramatic_impact: str = ""


class VolumeFrameworkOut(BaseModel):
    volume_number: int
    reader_lens: FrameworkReaderLensOut = FrameworkReaderLensOut()
    craft_focus: FrameworkCraftFocusOut = FrameworkCraftFocusOut()
    stages: list[FrameworkStageOut] = []
    cast: list[FrameworkCastOut] = []
    casting_note: str = ""
    involved_ids: list[str] = []


@router.get("/volumes/{number}/framework", response_model=VolumeFrameworkOut | None)
def get_volume_framework(number: int, deps: ProjectDeps = Depends(get_project_deps)):
    """Return the writing-framework briefing for a volume (Step 1), if any."""
    data = deps.outline.load_volume_framework(number)
    if data is None:
        return None
    return VolumeFrameworkOut(**data.model_dump())


@router.put("/volumes/{number}/beats")
def update_volume_beats(number: int, req: BeatUpdateRequest, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Replace the raw beat list for a volume (user edits)."""
    data = deps.outline.load_volume_beats(number)
    if data is None:
        data = VolumeBeatData(volume=number, step=3)
    new_beats = []
    for i, b in enumerate(req.beats):
        beat_id = b.id or f"b{i + 1:02d}"
        new_beats.append(RawBeat(id=beat_id, goal=b.goal, conflict=b.conflict, outcome=b.outcome, entities=b.entities, momentum=b.momentum))
    data.raw_beats = new_beats
    data.step = 3
    data.refined_beats = []
    data.chapter_map = []
    deps.outline.save_volume_beats(data)
    return {"ok": True, "beat_count": len(new_beats)}


@router.post("/volumes/{number}/beats")
def add_volume_beat(number: int, req: RawBeatIn, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Add a single beat to the volume's beat chain."""
    data = deps.outline.load_volume_beats(number)
    if data is None:
        data = VolumeBeatData(volume=number, step=3)
    beat_id = req.id
    if not beat_id:
        existing_ids = {b.id for b in data.raw_beats}
        idx = len(data.raw_beats) + 1
        while f"b{idx:02d}" in existing_ids:
            idx += 1
        beat_id = f"b{idx:02d}"
    data.raw_beats.append(RawBeat(id=beat_id, goal=req.goal, conflict=req.conflict, outcome=req.outcome, entities=req.entities, momentum=req.momentum))
    data.step = 3
    data.refined_beats = []
    data.chapter_map = []
    deps.outline.save_volume_beats(data)
    return {"ok": True, "id": beat_id}


@router.delete("/volumes/{number}/beats/{beat_id}")
def delete_volume_beat(number: int, beat_id: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Delete a single beat from the volume's beat chain."""
    data = deps.outline.load_volume_beats(number)
    if data is None:
        raise HTTPException(404, f"第 {number} 卷没有 beat 数据")
    original_len = len(data.raw_beats)
    data.raw_beats = [b for b in data.raw_beats if b.id != beat_id]
    if len(data.raw_beats) == original_len:
        raise HTTPException(404, f"Beat '{beat_id}' 不存在")
    data.step = 3
    data.refined_beats = []
    data.chapter_map = []
    deps.outline.save_volume_beats(data)
    return {"ok": True}


@router.put("/volumes/{number}/beats/reorder")
def reorder_volume_beats(number: int, req: BeatReorderRequest, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Reorder beats by providing the desired id sequence."""
    data = deps.outline.load_volume_beats(number)
    if data is None:
        raise HTTPException(404, f"第 {number} 卷没有 beat 数据")
    beat_index = {b.id: b for b in data.raw_beats}
    reordered = [beat_index[bid] for bid in req.ordered_ids if bid in beat_index]
    ordered_set = set(req.ordered_ids)
    for b in data.raw_beats:
        if b.id not in ordered_set:
            reordered.append(b)
    data.raw_beats = reordered
    data.step = 3
    data.refined_beats = []
    data.chapter_map = []
    deps.outline.save_volume_beats(data)
    return {"ok": True}


@router.post("/volumes/{number}/assemble")
def assemble_volume_beats(
    project_id: str,
    number: int,
    resume: bool = False,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EventSourceResponse:
    """Re-run Step 3 (refine + assemble) using the current beat list."""
    import threading
    import time
    import json

    if not resume:
        started = task_registry.try_start(
            project_id, "assemble_volume", number, "正在细化 beat 并组装章节…",
        )
        if started:
            def _run() -> None:
                try:
                    task_registry.update(
                        project_id, "assemble_volume",
                        "正在细化 beat 并组装章节…", number,
                    )
                    for event in deps.planner.assemble_from_beats(number):
                        kind = event["event"]
                        data = event["data"]
                        if kind == "step":
                            msg = data.get("message") or f"Step {data.get('step')}"
                            task_registry.update(project_id, "assemble_volume", msg, number)
                            snap = {k: v for k, v in data.items() if k != "beats"}
                            snap["volume"] = number
                            task_registry.set_stream(
                                project_id, "assemble_volume", number,
                                json.dumps(snap, ensure_ascii=False),
                            )
                            task_registry.publish(project_id, "assemble_volume", number, kind, data)
                        elif kind == "progress":
                            msg = data.get("message", "") if isinstance(data, dict) else str(data)
                            if msg:
                                # update() already fans out a progress event
                                task_registry.update(project_id, "assemble_volume", msg, number)
                        else:
                            task_registry.publish(project_id, "assemble_volume", number, kind, data)

                    task_registry.publish(
                        project_id, "assemble_volume", number, "done",
                        {"volume_number": number},
                    )
                    task_registry.mark_finished(project_id, "assemble_volume", number)
                except Exception as exc:  # noqa: BLE001
                    task_registry.publish(
                        project_id, "assemble_volume", number, "error",
                        {"message": str(exc)},
                    )
                    task_registry.mark_finished(
                        project_id, "assemble_volume", number, error=str(exc),
                    )
                finally:
                    def _cleanup() -> None:
                        time.sleep(120)
                        t = task_registry.get(project_id, "assemble_volume", number)
                        if t is not None and t.finished:
                            task_registry.unregister(project_id, "assemble_volume", number)
                    threading.Thread(
                        target=_cleanup, name=f"assemble-cleanup-{number}", daemon=True,
                    ).start()

            threading.Thread(
                target=_run, name=f"assemble-volume-{project_id}-{number}", daemon=True,
            ).start()

    return _volume_pipeline_sse(project_id, "assemble_volume", number)


@router.get("/volumes/{number}", response_model=VolumeOutlineOut | None)
def get_volume(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeOutlineOut | None:
    vol = deps.outline.read_volume(number)
    return _vol_out(vol) if vol else None


@router.put("/volumes/{number}", response_model=VolumeOutlineOut)
def update_volume(number: int, req: VolumeOutlineIn, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeOutlineOut:
    # Preserve the realized recap — it is only produced by the summarizer.
    existing = deps.outline.read_volume(number)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"第 {number} 卷不存在")
    recap = existing.recap
    vol = VolumeOutline(
        number=number,
        title=req.title,
        arc=req.arc,
        chapters=list(existing.chapters or []),
        ending=req.ending,
        recap=recap,
    )
    deps.outline.write_volume(vol)
    # chapters list is owned by chapter.volume pointers — recompute.
    deps.outline.sync_volume_chapters(number)
    vol = deps.outline.read_volume(number) or vol
    return _vol_out(vol)


@router.delete("/volumes/{number}")
def delete_volume(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Delete a volume and cascade-delete its chapter outlines (and drafts)."""
    try:
        deleted_chapters = deps.outline.delete_volume(number, cascade_chapters=True)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "volume": number, "deleted_chapters": deleted_chapters}


# ---- chapters ----

@router.get("/chapters", response_model=list[ChapterOutlineOut])
def list_chapters(deps: ProjectDeps = Depends(get_project_deps)) -> list[ChapterOutlineOut]:
    chapters = deps.outline.list_chapters()
    return [_ch_out(c, deps.paths) for c in chapters]


def _require_volume(deps: ProjectDeps, volume: int | None) -> int:
    if volume is None:
        raise HTTPException(status_code=400, detail="必须指定所属卷，请先规划卷")
    if deps.outline.read_volume(volume) is None:
        raise HTTPException(status_code=400, detail=f"第 {volume} 卷不存在，请先规划卷")
    return volume


@router.post("/chapters", response_model=ChapterOutlineOut)
def plan_chapter(req: PlanChapterRequest, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    """LLM-plan a chapter beat. The chapter number is auto-inferred."""
    volume = _require_volume(deps, req.volume)
    number = deps.outline.last_chapter_number() + 1
    task_registry.register(deps.project_dir.name, "plan_chapter", number, "正在规划章节…")
    try:
        ch = deps.planner.plan_chapter(number, volume=volume, title=req.title, hint=req.hint)
        return _ch_out(ch, deps.paths)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        task_registry.unregister(deps.project_dir.name, "plan_chapter", number)


@router.post("/chapters/{number}/regenerate", response_model=ChapterOutlineOut)
def regenerate_chapter(number: int, req: PlanChapterRequest, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    """LLM 重新生成已有章节的大纲（基于已有内容感知，不覆盖摘要）。"""
    existing = deps.outline.read_chapter(number)
    volume = req.volume
    if volume is None and existing is not None:
        volume = existing.volume
    volume = _require_volume(deps, volume)
    task_registry.register(deps.project_dir.name, "plan_chapter", number, "正在重新规划…")
    try:
        ch = deps.planner.plan_chapter(number, volume=volume, title=req.title, hint=req.hint)
        return _ch_out(ch, deps.paths)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        task_registry.unregister(deps.project_dir.name, "plan_chapter", number)


@router.get("/chapters/{number}", response_model=ChapterOutlineOut | None)
def get_chapter(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut | None:
    ch = deps.outline.read_chapter(number)
    return _ch_out(ch, deps.paths) if ch else None


@router.put("/chapters/{number}", response_model=ChapterOutlineOut)
def update_chapter(number: int, req: ChapterOutlineIn, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    if req.volume is None:
        raise HTTPException(status_code=400, detail="章节必须归属某一卷")
    if deps.outline.read_volume(req.volume) is None:
        raise HTTPException(status_code=400, detail=f"第 {req.volume} 卷不存在")
    beats = [
        SceneBeat(
            goal=b.goal, conflict=b.conflict, outcome=b.outcome, entities=b.entities,
            scenes=[
                MicroScene(
                    intent=s.intent, sensory=s.sensory,
                    action=s.action, dialogue=s.dialogue, event=s.event,
                    technique=s.technique, pacing=s.pacing, words=max(s.words, 0),
                )
                for s in (b.scenes or [])
            ],
        )
        for b in req.beats
    ]
    ch = ChapterOutline(
        number=number, title=req.title, volume=req.volume,
        entities=req.entities, tags=req.tags, beats=beats, notes=req.notes,
        keynote=[k.strip() for k in (req.keynote or []) if k and k.strip()],
        purpose=req.purpose, value_shift=req.value_shift,
        tension=min(max(req.tension, 0), 5), hook=req.hook,
        story_date=req.story_date, elapsed=req.elapsed,
    )
    # Always preserve existing summary — it only changes via the summarizer
    # after a chapter write, never from manual outline editing.
    existing = deps.outline.read_chapter(number)
    if existing and existing.summary:
        ch.summary = existing.summary
    deps.outline.write_chapter(ch)
    return _ch_out(ch, deps.paths)


@router.delete("/chapters/{number}")
def delete_chapter(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Delete a chapter outline and related draft/final/context files."""
    if not deps.outline.delete_chapter(number):
        raise HTTPException(status_code=404, detail=f"第 {number} 章不存在")
    return {"ok": True, "chapter": number}


# ---- helpers ----

def _vol_out(v: VolumeOutline) -> VolumeOutlineOut:
    return VolumeOutlineOut(number=v.number, title=v.title, arc=v.arc, chapters=v.chapters, ending=v.ending, recap=v.recap)


def _ch_out(c: ChapterOutline, paths=None) -> ChapterOutlineOut:
    has_draft = False
    if paths is not None:
        has_draft = paths.draft_file(c.number).exists()
    return ChapterOutlineOut(
        number=c.number, title=c.title, volume=c.volume,
        entities=c.entities, tags=c.tags,
        beats=[
            SceneBeatOut(
                goal=b.goal, conflict=b.conflict, outcome=b.outcome, entities=b.entities,
                scenes=[
                    MicroSceneOut(
                        intent=s.intent, sensory=s.sensory,
                        action=s.action, dialogue=s.dialogue, event=s.event,
                        technique=s.technique, pacing=s.pacing, words=s.words,
                    )
                    for s in (b.scenes or [])
                ],
            )
            for b in c.beats
        ],
        notes=c.notes, keynote=list(c.keynote or []), summary=c.summary,
        purpose=c.purpose, value_shift=c.value_shift, tension=c.tension,
        hook=c.hook, story_date=c.story_date, elapsed=c.elapsed,
        has_draft=has_draft,
    )
