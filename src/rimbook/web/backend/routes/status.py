"""Dashboard / status routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import ProjectDeps, get_project_deps

router = APIRouter(prefix="/api/projects/{project_id}", tags=["status"])


class ChapterProgress(BaseModel):
    number: int
    title: str
    volume: int | None
    beat_count: int
    has_summary: bool
    has_draft: bool


class ProjectStatus(BaseModel):
    title: str
    author: str
    has_synopsis: bool
    volume_count: int
    chapter_count: int
    draft_count: int
    codex_count: int
    chapters: list[ChapterProgress]


@router.get("/status", response_model=ProjectStatus)
def get_status(deps: ProjectDeps = Depends(get_project_deps)) -> ProjectStatus:
    """Project overview for the dashboard."""
    synopsis = deps.outline.read_synopsis().strip()
    volumes = deps.outline.list_volumes()
    chapters = deps.outline.list_chapters()
    codex_entries = deps.codex.all()
    draft_nums = set()
    if deps.paths.drafts_dir.exists():
        for p in deps.paths.drafts_dir.glob("ch*.md"):
            stem = p.stem
            if stem.startswith("ch") and stem[2:].isdigit():
                draft_nums.add(int(stem[2:]))

    ch_progress = [
        ChapterProgress(
            number=c.number,
            title=c.title,
            volume=c.volume,
            beat_count=len(c.beats),
            has_summary=bool(c.summary.strip()),
            has_draft=c.number in draft_nums,
        )
        for c in chapters
    ]
    return ProjectStatus(
        title=deps.config.title,
        author=deps.config.author,
        has_synopsis=bool(synopsis),
        volume_count=len(volumes),
        chapter_count=len(chapters),
        draft_count=len(draft_nums),
        codex_count=len(codex_entries),
        chapters=ch_progress,
    )
