"""Writer workbench routes — generation, checking, revision, SSE streaming."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from rimbook.outline import ChapterOutline

from ..deps import ProjectDeps, get_project_deps
from ..sse import sse_done, sse_event, sse_progress

router = APIRouter(prefix="/api/projects/{project_id}", tags=["writer"])


# ---- request models ----

class DraftUpdate(BaseModel):
    text: str


class ReviseRequest(BaseModel):
    instructions: str = ""


class CheckRequest(BaseModel):
    fix: bool = False


# ---- draft CRUD ----

@router.get("/drafts/{number}")
def get_draft(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Read a chapter draft."""
    path = deps.paths.draft_file(number)
    if not path.exists():
        return {"text": "", "exists": False}
    return {"text": path.read_text(encoding="utf-8"), "exists": True}


@router.put("/drafts/{number}")
def update_draft(number: int, req: DraftUpdate, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Manually save a draft (after user edits in the browser)."""
    path = deps.paths.draft_file(number)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(req.text, encoding="utf-8")
    return {"ok": True}


# ---- context preview ----

@router.get("/context/{number}")
def preview_context(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Preview the assembled context for a chapter (without generating)."""
    ch = deps.outline.read_chapter(number)
    if ch is None:
        raise HTTPException(404, f"Chapter {number} has no outline")
    ctx = deps.assembler.assemble_for_chapter(ch)
    return {
        "text": ctx.text,
        "codex_used": [e.id for e in ctx.codex_used],
        "entity_states": [s.entity_id for s in ctx.entity_states_used],
        "recent_chapters": ctx.recent_chapters,
    }


# ---- write (SSE) ----

@router.get("/write/{number}")
def write_chapter_sse(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> EventSourceResponse:
    """Generate a chapter with SSE progress streaming."""

    async def event_stream():
        try:
            yield sse_progress("正在加载章节大纲…")
            ch = deps.outline.read_chapter(number)
            if ch is None:
                yield sse_event("error", {"message": f"Chapter {number} has no outline"})
                yield sse_done()
                return

            yield sse_progress("正在组装上下文…")
            # Run blocking code in a thread so we don't block the event loop.
            context = await asyncio.to_thread(deps.assembler.assemble_for_chapter, ch)
            yield sse_event("context", {
                "preview": context.text[:500],
                "codex_used": [e.id for e in context.codex_used],
            })

            yield sse_progress("正在生成正文…")
            result = await asyncio.to_thread(deps.writer.write, number)

            yield sse_event("draft", {
                "path": result.draft_path,
                "summary": result.summary,
                "entities_tracked": result.entities_tracked,
                "usage": result.usage,
            })

            # Optional consistency check
            if deps.config.generation.auto_consistency_check:
                yield sse_progress("正在校验一致性…")
                report = await asyncio.to_thread(deps.checker.check, number)
                yield sse_event("check", {
                    "overall": report.overall,
                    "summary": report.summary,
                    "issues": [
                        {
                            "severity": i.severity,
                            "category": i.category,
                            "description": i.description,
                            "evidence": i.evidence,
                            "suggestion": i.suggestion,
                        }
                        for i in report.issues
                    ],
                })

            yield sse_progress("完成！")
            yield sse_done({"chapter": number})
        except Exception as exc:
            yield sse_event("error", {"message": str(exc)})
            yield sse_done()

    return EventSourceResponse(event_stream())


# ---- check ----

@router.post("/check/{number}")
def check_chapter(number: int, req: CheckRequest, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Run consistency check on a chapter draft."""
    path = deps.paths.draft_file(number)
    if not path.exists():
        raise HTTPException(404, f"No draft for chapter {number}")

    if req.fix:
        max_rounds = deps.config.generation.max_fix_rounds

        def apply_fix(text: str, issues_blob: str) -> str:
            res = deps.writer.revise(number, draft_text=text, instructions=f"请解决以下审校问题：\n{issues_blob}")
            from pathlib import Path
            return Path(res.draft_path).read_text(encoding="utf-8").strip()

        report = deps.checker.check_and_fix(number, max_rounds=max_rounds, apply_fix=apply_fix)
    else:
        report = deps.checker.check(number)

    return {
        "overall": report.overall,
        "summary": report.summary,
        "rounds": report.rounds,
        "issues": [
            {
                "severity": i.severity,
                "category": i.category,
                "description": i.description,
                "evidence": i.evidence,
                "suggestion": i.suggestion,
            }
            for i in report.issues
        ],
        "final_text": report.final_text if req.fix else None,
    }


# ---- revise ----

@router.post("/revise/{number}")
def revise_chapter(number: int, req: ReviseRequest, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Revise a chapter draft."""
    try:
        result = deps.writer.revise(number, instructions=req.instructions)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {
        "draft_path": result.draft_path,
        "summary": result.summary,
        "usage": result.usage,
    }


# ---- summary ----

@router.post("/summary/{number}")
def regenerate_summary(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Regenerate a chapter summary from the current draft."""
    path = deps.paths.draft_file(number)
    if not path.exists():
        raise HTTPException(404, f"No draft for chapter {number}")
    text = path.read_text(encoding="utf-8").strip()
    summary = deps.summarizer.summarize(number, text)
    return {"summary": summary}


# ---- snapshots ----

@router.get("/snapshots")
def list_snapshots(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """List available snapshots."""
    snap_dir = deps.paths.versions_dir
    if not snap_dir.exists():
        return {"snapshots": []}
    snaps = sorted(snap_dir.iterdir(), reverse=True)
    return {"snapshots": [s.name for s in snaps if s.is_dir()]}


@router.post("/snapshots")
def create_snapshot(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Create a version snapshot."""
    import time, shutil
    ts = time.strftime("%Y%m%d-%H%M%S")
    snap_dir = deps.paths.versions_dir / f"{ts}-web"
    snap_dir.mkdir(parents=True, exist_ok=True)
    for item in deps.project_dir.iterdir():
        if item.name == ".versions":
            continue
        if item.is_dir():
            shutil.copytree(item, snap_dir / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, snap_dir / item.name)
    return {"snapshot": snap_dir.name}
