"""Outline management routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from rimbook.outline import ChapterOutline, SceneBeat, VolumeOutline, RawBeat, VolumeBeatData

from ..deps import ProjectDeps, get_project_deps
from ..sse import sse_done, sse_event, sse_progress

router = APIRouter(prefix="/api/projects/{project_id}/outline", tags=["outline"])


# ---- models ----

class SceneBeatIn(BaseModel):
    goal: str = ""
    conflict: str = ""
    outcome: str = ""
    entities: list[str] = []


class SceneBeatOut(BaseModel):
    goal: str
    conflict: str
    outcome: str
    entities: list[str]


class ChapterOutlineIn(BaseModel):
    title: str = ""
    volume: int | None = None
    entities: list[str] = []
    tags: list[str] = []
    beats: list[SceneBeatIn] = []
    notes: str = ""


class ChapterOutlineOut(BaseModel):
    number: int
    title: str
    volume: int | None
    entities: list[str]
    tags: list[str]
    beats: list[SceneBeatOut]
    notes: str
    summary: str


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
    ending: str


class SynopsisIn(BaseModel):
    text: str


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
    """LLM-generate synopsis from a premise. req.text = premise."""
    text = deps.planner.plan_synopsis(req.text)
    return {"text": text}


# ---- volumes ----

@router.get("/volumes", response_model=list[VolumeOutlineOut])
def list_volumes(deps: ProjectDeps = Depends(get_project_deps)) -> list[VolumeOutlineOut]:
    vols = deps.outline.list_volumes()
    return [_vol_out(v) for v in vols]


class PlanVolumeV2Request(BaseModel):
    title: str = ""


@router.post("/volumes/plan")
def plan_volume_v2_sse(req: PlanVolumeV2Request, deps: ProjectDeps = Depends(get_project_deps)) -> EventSourceResponse:
    """Full v2 volume planning pipeline with SSE progress (Step 1+2+3)."""

    async def event_stream():
        try:
            existing = deps.outline.list_volumes()
            number = max((v.number for v in existing), default=0) + 1
            yield sse_progress(f"正在规划第 {number} 卷…")

            gen = deps.planner.plan_volume_v2(number, title=req.title)
            for event in gen:
                yield sse_event(event["event"], event["data"])
                await asyncio.sleep(0)  # yield control

            yield sse_done({"volume_number": number})
        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream())


@router.get("/volumes/{number}", response_model=VolumeOutlineOut | None)
def get_volume(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeOutlineOut | None:
    vol = deps.outline.read_volume(number)
    return _vol_out(vol) if vol else None


@router.put("/volumes/{number}", response_model=VolumeOutlineOut)
def update_volume(number: int, req: VolumeOutlineIn, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeOutlineOut:
    vol = VolumeOutline(number=number, title=req.title, arc=req.arc, chapters=req.chapters, ending=req.ending)
    deps.outline.write_volume(vol)
    return _vol_out(vol)


# ---- chapters ----

@router.get("/chapters", response_model=list[ChapterOutlineOut])
def list_chapters(deps: ProjectDeps = Depends(get_project_deps)) -> list[ChapterOutlineOut]:
    chapters = deps.outline.list_chapters()
    return [_ch_out(c) for c in chapters]


@router.post("/chapters", response_model=ChapterOutlineOut)
def plan_chapter(req: PlanChapterRequest, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    """LLM-plan a chapter beat. The chapter number is auto-inferred."""
    number = deps.outline.last_chapter_number() + 1
    ch = deps.planner.plan_chapter(number, volume=req.volume, title=req.title, hint=req.hint)
    return _ch_out(ch)


@router.get("/chapters/{number}", response_model=ChapterOutlineOut | None)
def get_chapter(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut | None:
    ch = deps.outline.read_chapter(number)
    return _ch_out(ch) if ch else None


@router.put("/chapters/{number}", response_model=ChapterOutlineOut)
def update_chapter(number: int, req: ChapterOutlineIn, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    beats = [SceneBeat(goal=b.goal, conflict=b.conflict, outcome=b.outcome, entities=b.entities) for b in req.beats]
    ch = ChapterOutline(
        number=number, title=req.title, volume=req.volume,
        entities=req.entities, tags=req.tags, beats=beats, notes=req.notes,
    )
    # Preserve existing summary if not overwritten.
    existing = deps.outline.read_chapter(number)
    if existing and existing.summary and not req.notes:
        ch.summary = existing.summary
    deps.outline.write_chapter(ch)
    return _ch_out(ch)


# ---- helpers ----

def _vol_out(v: VolumeOutline) -> VolumeOutlineOut:
    return VolumeOutlineOut(number=v.number, title=v.title, arc=v.arc, chapters=v.chapters, ending=v.ending)


def _ch_out(c: ChapterOutline) -> ChapterOutlineOut:
    return ChapterOutlineOut(
        number=c.number, title=c.title, volume=c.volume,
        entities=c.entities, tags=c.tags,
        beats=[SceneBeatOut(goal=b.goal, conflict=b.conflict, outcome=b.outcome, entities=b.entities) for b in c.beats],
        notes=c.notes, summary=c.summary,
    )


# ==================================================================
# Volume Planning v2: beat chain → refine → assemble
# ==================================================================

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


@router.get("/volumes/{number}/beats")
def get_volume_beats(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeBeatDataOut | dict:
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


@router.put("/volumes/{number}/beats")
def update_volume_beats(number: int, req: BeatUpdateRequest, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Replace the raw beat list for a volume (user edits)."""
    data = deps.outline.load_volume_beats(number)
    if data is None:
        data = VolumeBeatData(volume=number, step=2)

    new_beats = []
    for i, b in enumerate(req.beats):
        beat_id = b.id or f"b{i + 1:02d}"
        new_beats.append(RawBeat(
            id=beat_id, goal=b.goal, conflict=b.conflict,
            outcome=b.outcome, entities=b.entities, momentum=b.momentum,
        ))
    data.raw_beats = new_beats
    # Reset step to 2 (needs re-assembly)
    data.step = 2
    data.refined_beats = []
    data.chapter_map = []
    deps.outline.save_volume_beats(data)
    return {"ok": True, "beat_count": len(new_beats)}


@router.post("/volumes/{number}/beats")
def add_volume_beat(number: int, req: RawBeatIn, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Add a single beat to the volume's beat chain."""
    data = deps.outline.load_volume_beats(number)
    if data is None:
        data = VolumeBeatData(volume=number, step=2)

    # Auto-assign id if not provided
    beat_id = req.id
    if not beat_id:
        existing_ids = {b.id for b in data.raw_beats}
        idx = len(data.raw_beats) + 1
        while f"b{idx:02d}" in existing_ids:
            idx += 1
        beat_id = f"b{idx:02d}"

    data.raw_beats.append(RawBeat(
        id=beat_id, goal=req.goal, conflict=req.conflict,
        outcome=req.outcome, entities=req.entities, momentum=req.momentum,
    ))
    data.step = 2
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

    data.step = 2
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
    reordered = []
    for bid in req.ordered_ids:
        if bid in beat_index:
            reordered.append(beat_index[bid])
    # Append any beats not in the ordered list (safety)
    ordered_set = set(req.ordered_ids)
    for b in data.raw_beats:
        if b.id not in ordered_set:
            reordered.append(b)

    data.raw_beats = reordered
    data.step = 2
    data.refined_beats = []
    data.chapter_map = []
    deps.outline.save_volume_beats(data)
    return {"ok": True}


@router.post("/volumes/{number}/assemble")
def assemble_volume_beats(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> EventSourceResponse:
    """Re-run Step 3 (refine + assemble) using the current beat list."""

    async def event_stream():
        try:
            yield sse_progress("正在细化 beat 并组装章节…")
            gen = deps.planner.assemble_from_beats(number)
            for event in gen:
                yield sse_event(event["event"], event["data"])
                await asyncio.sleep(0)
            yield sse_done({"volume_number": number})
        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream())
