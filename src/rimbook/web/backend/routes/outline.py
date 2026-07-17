"""Outline management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from rimbook.outline import ChapterOutline, SceneBeat, VolumeOutline

from ..deps import ProjectDeps, get_project_deps
from ..tasks import task_registry

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


class PlanChapterRequest(BaseModel):
    volume: int | None = None
    title: str = ""
    hint: str = ""


class PlanVolumeRequest(BaseModel):
    title: str = ""


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


@router.post("/volumes", response_model=VolumeOutlineOut)
def plan_volume(req: PlanVolumeRequest, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeOutlineOut:
    """LLM-plan a volume. The volume number is auto-inferred."""
    existing = deps.outline.list_volumes()
    number = max((v.number for v in existing), default=0) + 1
    task_registry.register(deps.project_dir.name, "plan_volume", None, "正在规划卷及全部章节…")
    try:
        result = deps.planner.plan_volume(number, title=req.title)
        return _vol_out(result.volume)
    finally:
        task_registry.unregister(deps.project_dir.name, "plan_volume", None)


@router.get("/volumes/{number}", response_model=VolumeOutlineOut | None)
def get_volume(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeOutlineOut | None:
    vol = deps.outline.read_volume(number)
    return _vol_out(vol) if vol else None


@router.put("/volumes/{number}", response_model=VolumeOutlineOut)
def update_volume(number: int, req: VolumeOutlineIn, deps: ProjectDeps = Depends(get_project_deps)) -> VolumeOutlineOut:
    # Preserve the realized recap — it is only produced by the summarizer.
    existing = deps.outline.read_volume(number)
    recap = existing.recap if existing else ""
    vol = VolumeOutline(number=number, title=req.title, arc=req.arc, chapters=req.chapters, ending=req.ending, recap=recap)
    deps.outline.write_volume(vol)
    return _vol_out(vol)


# ---- chapters ----

@router.get("/chapters", response_model=list[ChapterOutlineOut])
def list_chapters(deps: ProjectDeps = Depends(get_project_deps)) -> list[ChapterOutlineOut]:
    chapters = deps.outline.list_chapters()
    return [_ch_out(c, deps.paths) for c in chapters]


@router.post("/chapters", response_model=ChapterOutlineOut)
def plan_chapter(req: PlanChapterRequest, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    """LLM-plan a chapter beat. The chapter number is auto-inferred."""
    number = deps.outline.last_chapter_number() + 1
    task_registry.register(deps.project_dir.name, "plan_chapter", number, "正在规划章节…")
    try:
        ch = deps.planner.plan_chapter(number, volume=req.volume, title=req.title, hint=req.hint)
        return _ch_out(ch, deps.paths)
    finally:
        task_registry.unregister(deps.project_dir.name, "plan_chapter", number)


@router.post("/chapters/{number}/regenerate", response_model=ChapterOutlineOut)
def regenerate_chapter(number: int, req: PlanChapterRequest, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    """LLM 重新生成已有章节的大纲（基于已有内容感知，不覆盖摘要）。"""
    task_registry.register(deps.project_dir.name, "plan_chapter", number, "正在重新规划…")
    try:
        ch = deps.planner.plan_chapter(number, volume=req.volume, title=req.title, hint=req.hint)
        return _ch_out(ch, deps.paths)
    finally:
        task_registry.unregister(deps.project_dir.name, "plan_chapter", number)


@router.get("/chapters/{number}", response_model=ChapterOutlineOut | None)
def get_chapter(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut | None:
    ch = deps.outline.read_chapter(number)
    return _ch_out(ch, deps.paths) if ch else None


@router.put("/chapters/{number}", response_model=ChapterOutlineOut)
def update_chapter(number: int, req: ChapterOutlineIn, deps: ProjectDeps = Depends(get_project_deps)) -> ChapterOutlineOut:
    beats = [SceneBeat(goal=b.goal, conflict=b.conflict, outcome=b.outcome, entities=b.entities) for b in req.beats]
    ch = ChapterOutline(
        number=number, title=req.title, volume=req.volume,
        entities=req.entities, tags=req.tags, beats=beats, notes=req.notes,
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
        beats=[SceneBeatOut(goal=b.goal, conflict=b.conflict, outcome=b.outcome, entities=b.entities) for b in c.beats],
        notes=c.notes, summary=c.summary,
        purpose=c.purpose, value_shift=c.value_shift, tension=c.tension,
        hook=c.hook, story_date=c.story_date, elapsed=c.elapsed,
        has_draft=has_draft,
    )
