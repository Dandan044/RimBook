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
from ..tasks import task_registry

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
        "section_list": _serialize_section_list(ctx.section_list),
        "codex_used": [e.id for e in ctx.codex_used],
        "entity_states": [s.entity_id for s in ctx.entity_states_used],
        "recent_chapters": ctx.recent_chapters,
    }


# ---- write (SSE) ----

@router.get("/write/{number}")
def write_chapter_sse(number: int, deps: ProjectDeps = Depends(get_project_deps)) -> EventSourceResponse:
    """Generate a chapter with SSE progress streaming."""

    async def event_stream():
        task_registry.register(project_id, "write", number, "准备中…")
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

            # Enrichment results (auto codex expansion).
            if result.enrichment:
                yield sse_progress("正在扩充设定集…")
                yield sse_event("enrichment", {
                    "created": [
                        {"id": c.entity_id, "detail": c.detail}
                        for c in result.enrichment.entities_created
                    ],
                    "updated": [
                        {"id": c.entity_id, "detail": c.detail}
                        for c in result.enrichment.entities_updated
                    ],
                    "contradictions": [
                        {"id": c.entity_id, "detail": c.detail}
                        for c in result.enrichment.contradictions
                    ],
                    "summary": result.enrichment.summary,
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
        finally:
            task_registry.unregister(project_id, "write", number)

    return EventSourceResponse(event_stream())


# ---- write status (polling fallback for reconnection) ----

@router.get("/write-status/{number}")
def write_status(project_id: str, number: int, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Check if a write/revise is in progress for this chapter."""
    t = task_registry.get(project_id, "write", number) or task_registry.get(project_id, "revise", number)
    if t:
        return {"active": True, "progress": t.progress, "started_at": t.started_at, "op": t.op}
    draft_path = deps.paths.draft_file(number)
    if draft_path.exists():
        return {"active": False, "progress": "completed", "draft_exists": True, "op": ""}
    return {"active": False, "progress": "", "draft_exists": False, "op": ""}


# ---- all active tasks ----

@router.get("/tasks")
def list_tasks(project_id: str) -> dict:
    """List all active long-running tasks for this project."""
    tasks = task_registry.list_for_project(project_id)
    return {
        "tasks": [
            {"op": t.op, "chapter": t.chapter, "started_at": t.started_at, "progress": t.progress}
            for t in tasks
        ]
    }


# ---- check ----

@router.post("/check/{number}")
def check_chapter(project_id: str, number: int, req: CheckRequest, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Run consistency check on a chapter draft."""
    path = deps.paths.draft_file(number)
    if not path.exists():
        raise HTTPException(404, f"No draft for chapter {number}")

    if req.fix:
        task_registry.register(project_id, "check", number, "校验并修复中…")
        try:
            max_rounds = deps.config.generation.max_fix_rounds

            def apply_fix(text: str, issues_blob: str) -> str:
                res = deps.writer.revise(number, draft_text=text, instructions=f"请解决以下审校问题：\n{issues_blob}")
                from pathlib import Path
                return Path(res.draft_path).read_text(encoding="utf-8").strip()

            report = deps.checker.check_and_fix(number, max_rounds=max_rounds, apply_fix=apply_fix)
        finally:
            task_registry.unregister(project_id, "check", number)
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
def revise_chapter(project_id: str, number: int, req: ReviseRequest, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Revise a chapter draft."""
    task_registry.register(project_id, "revise", number, "修订中…")
    try:
        result = deps.writer.revise(number, instructions=req.instructions)
        return {
            "draft_path": result.draft_path,
            "summary": result.summary,
            "usage": result.usage,
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    finally:
        task_registry.unregister(project_id, "revise", number)


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


# ---- helpers ----

def _serialize_section_list(section_list: list) -> list[dict]:
    """Convert SectionInfo dataclass instances to JSON-safe dicts."""
    result: list[dict] = []
    for sec in section_list:
        d = {
            "key": sec.key,
            "label": sec.label,
            "text": sec.text,
            "tokens": sec.tokens,
        }
        if sec.entities:
            d["entities"] = sec.entities
        if sec.sub_items:
            d["sub_items"] = sec.sub_items
        result.append(d)
    return result
