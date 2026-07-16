"""Writer workbench routes — generation, checking, revision, SSE streaming."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from rimbook.outline import ChapterOutline

from ..deps import ProjectDeps, get_project_deps
from ..sse import sse_done, sse_event, sse_progress
from ..tasks import task_registry

router = APIRouter(prefix="/api/projects/{project_id}", tags=["writer"])


# ---- branch fork for safe re-generation ----

class ForkForRegenReq(BaseModel):
    branch_name: str = ""


@router.post("/chapters/{number}/fork-for-regen")
def fork_for_regen(
    project_id: str,
    number: int,
    req: ForkForRegenReq,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Create a branch from the last pre-write checkpoint of *number* and switch to it.

    Use this before re-generating a chapter that has subsequent chapters already
    written — so the codex and entity state don't get contaminated.

    The checkpoint created by ``Writer.write()`` is incremental (only contains
    the files predicted to change for that chapter).  To produce a workable
    branch HEAD we must build a *full* snapshot from it: start with a full
    copy of the current project, overlay the incremental checkpoint (which
    restores the pre-write codex + state for chapter *number*), then delete
    drafts for chapters >= *number* (they didn't exist at pre-write time).
    """
    vm = deps.version_manager
    if vm is None:
        raise HTTPException(400, "版本管理未启用（auto_checkpoint 关闭）")

    # ---- 1. Find the earliest pre-write checkpoint (true baseline) ----
    # Newest write-chN snapshots may be polluted if a prior regen failed to
    # delete post-write files; the earliest one is the real pre-first-write state.
    current_branch = vm.get_current_branch()
    checkpoints = vm.list_checkpoints(branch=current_branch)
    prefix = f"write-ch{number}-"
    matching = [c for c in checkpoints if c.label.startswith(prefix)]
    last_cp = matching[-1] if matching else None  # list is newest-first → last = oldest
    if last_cp is None:
        raise HTTPException(
            404,
            f"未找到第 {number} 章的预写快照（write-ch{number}-…）。"
            f"请确认 auto_checkpoint 已开启且该章曾至少生成过一次。",
        )

    cp_dir = deps.paths.versions_dir / last_cp.name
    if not cp_dir.exists():
        raise HTTPException(404, f"快照目录不存在：{last_cp.name}")

    # ---- 2. Build full snapshot from incremental checkpoint ----
    branch_name = req.branch_name.strip() if req.branch_name.strip() else f"regen-ch{number}"
    existing = vm.list_branches()
    existing_names = {b.name for b in existing}
    base = branch_name
    counter = 2
    while branch_name in existing_names:
        branch_name = f"{base}-{counter}"
        counter += 1

    ts = time.strftime("%Y%m%d-%H%M%S")
    full_name = f"{ts}-{branch_name}"
    full_dir = deps.paths.versions_dir / full_name
    # Avoid collision if two forks happen in the same second.
    _suffix = 1
    while full_dir.exists():
        full_name = f"{ts}-{branch_name}-{_suffix}"
        full_dir = deps.paths.versions_dir / full_name
        _suffix += 1
    full_dir.mkdir(parents=True)

    copied = 0
    cp_file_set: set[str] = set()
    try:
        # Build set of checkpoint-relative paths (for project-level cleanup later).
        for item in cp_dir.rglob("*"):
            if item.is_file() and item.name != ".manifest":
                rel = str(item.relative_to(cp_dir)).replace("\\", "/")
                cp_file_set.add(rel)

        # 2a. Copy ALL current project files (except .versions and drafts >= N).
        for item in deps.project_dir.iterdir():
            if item.name == ".versions":
                continue
            if item.is_dir():
                for src_file in item.rglob("*"):
                    if not src_file.is_file():
                        continue
                    rel = str(src_file.relative_to(deps.project_dir)).replace("\\", "/")
                    # Skip drafts for chapters >= N.
                    if _is_draft_ge(rel, number):
                        continue
                    dest = full_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src_file), str(dest))
                    copied += 1
            else:
                shutil.copy2(str(item), str(full_dir / item.name))
                copied += 1

        # 2b. Overlay the incremental checkpoint files (pre-write codex + state).
        overlay = 0
        for item in cp_dir.rglob("*"):
            if item.is_file() and item.name != ".manifest":
                rel = item.relative_to(cp_dir)
                dest = full_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(dest))
                overlay += 1

        # 2c. Delete version-controlled runtime files that were copied from
        #     the live project but are absent from the pre-write checkpoint
        #     (created by post-write of chapter >= N). Includes state/codex,
        #     story-so-far, and reviews. Volume outlines are NOT deleted here
        #     (planning data); their recaps are cleared in step 4.
        #     Style bible is intentionally left alone.
        for item in list(full_dir.rglob("*")):
            if not item.is_file() or item.name == ".manifest":
                continue
            rel = str(item.relative_to(full_dir)).replace("\\", "/")
            if _is_runtime_versioned_rel(rel) and rel not in cp_file_set:
                item.unlink()
                copied = max(0, copied - 1)

        # 2d. Write manifest.
        (full_dir / ".manifest").write_text(
            f"label: {branch_name}\n"
            f"timestamp: {ts}\n"
            f"branch: {branch_name}\n"
            f"parent: {last_cp.name}\n"
            f"files: {copied}\n"
            f"overlay: {overlay} files from {last_cp.name}\n",
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(full_dir, ignore_errors=True)
        raise

    # ---- 3. Create branch from full snapshot & switch ----
    try:
        vm.create_branch(branch_name, from_checkpoint=full_name)
    except ValueError as e:
        shutil.rmtree(full_dir, ignore_errors=True)
        raise HTTPException(409, str(e))

    try:
        saved = vm.switch_branch(branch_name)
    except ValueError as e:
        # Attempt clean-up: remove the branch (switching failed).
        try:
            branches = vm._read_branches()
            branches.pop(branch_name, None)
            vm._write_branches(branches)
        except Exception:
            pass
        raise HTTPException(400, str(e))

    # ---- 4. Clean up post-ChN artefacts from the project ----
    # restore_checkpoint only copies files — it does not delete stale files
    # or revert content that was added by chapters >= *number*.  We clean
    # those up here so the project truly reflects the pre-ChN state.

    cleaned = 0

    # 4a. Remove drafts + write-time context snapshots for chapters >= *number*.
    project_drafts_dir = deps.paths.draft_file(1).parent
    if project_drafts_dir.exists():
        for df in sorted(project_drafts_dir.glob("ch*.md")):
            m = re.match(r"ch0*(\d+)", df.name)
            if m and int(m.group(1)) >= number:
                df.unlink()
                cleaned += 1
        for cf in sorted(project_drafts_dir.glob("ch*.context.json")):
            m = re.match(r"ch0*(\d+)", cf.name)
            if m and int(m.group(1)) >= number:
                cf.unlink()
                cleaned += 1

    # 4b. Strip revelations / contradictions / body fragments from codex
    #     entries that were added by chapters >= *number*.
    _clean_codex_post_chapter(deps, number)

    # 4c. Revert entity state knowledge / last_seen from chapters >= *number*.
    _clean_entity_state_post_chapter(deps, number)

    # 4d. Narrative assets: threads / story-so-far / volume recaps / reviews.
    from rimbook.versioning.cleanup import (
        clean_reviews_not_in_snapshot,
        clean_story_so_far_post_chapter,
        clean_threads_post_chapter,
        clean_volume_recaps_post_chapter,
    )

    clean_threads_post_chapter(deps.threads, number)
    clean_story_so_far_post_chapter(deps.outline, number)
    clean_volume_recaps_post_chapter(deps.outline, number)
    clean_reviews_not_in_snapshot(deps.paths.reviews_dir, cp_file_set)

    return {
        "ok": True,
        "branch": branch_name,
        "from_checkpoint": last_cp.name,
        "from_checkpoint_label": last_cp.label,
        "previous_branch": current_branch,
        "saved_checkpoint": saved or None,
        "hint": (
            f"已切换到分支「{branch_name}」，"
            f"项目回退到第 {number} 章生成前的状态"
            f"（快照共 {copied} 个文件，其中 {overlay} 个来自预写快照覆盖，"
            f"已清理 {cleaned} 个后续章草稿，"
            f"已剥离 codex/state/线索/故事线/卷回顾/审阅 中来自 ≥{number} 章的内容）。"
            f"原分支「{current_branch}」的存档点：{saved or '无'}。"
        ),
    }


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


# ---- context (write-time snapshot preferred) ----

@router.get("/context/{number}")
def get_chapter_context(
    number: int,
    live: bool = False,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Return context for a chapter.

    By default returns the **write-time snapshot** saved when the draft was
    generated (the exact context fed to the LLM).  Pass ``live=true`` to
    re-assemble from the current project state instead.
    """
    from rimbook.memory.assembler import load_context_snapshot, serialize_context

    if not live:
        snap = load_context_snapshot(deps.paths, number)
        if snap is not None:
            return {
                "text": snap.get("text", ""),
                "section_list": snap.get("section_list") or [],
                "codex_used": snap.get("codex_used") or [],
                "entity_states": snap.get("entity_states") or [],
                "recent_chapters": snap.get("recent_chapters") or [],
                "source": "write",
            }

    ch = deps.outline.read_chapter(number)
    if ch is None:
        raise HTTPException(404, f"Chapter {number} has no outline")
    ctx = deps.assembler.assemble_for_chapter(ch)
    payload = serialize_context(ctx)
    payload["source"] = "live"
    return payload


# ---- write (POST start + poll status; SSE is optional attach) ----

def _spawn_write_worker(project_id: str, number: int, deps: ProjectDeps) -> None:
    """Run Writer.write in a daemon thread; updates task_registry as it goes."""
    import threading

    def _progress(msg: str) -> None:
        task_registry.update(project_id, "write", msg, number)

    def _run_write() -> None:
        try:
            _progress("正在加载章节大纲…")
            ch = deps.outline.read_chapter(number)
            if ch is None:
                task_registry.publish(
                    project_id, "write", number, "error", "Chapter has no outline"
                )
                task_registry.mark_finished(
                    project_id, "write", number, error="无章节大纲"
                )
                return

            _progress("正在组装上下文…")
            # Preview is optional; writer will assemble again.
            try:
                context = deps.assembler.assemble_for_chapter(ch)
                task_registry.publish(project_id, "write", number, "context", {
                    "preview": context.text[:500],
                    "codex_used": [e.id for e in context.codex_used],
                })
            except Exception:
                pass

            def on_token(delta: str) -> None:
                task_registry.append_stream(project_id, "write", number, delta)

            result = deps.writer.write(
                number, on_token=on_token, on_progress=_progress,
            )

            draft_text = ""
            draft_path = Path(result.draft_path)
            if draft_path.exists():
                draft_text = draft_path.read_text(encoding="utf-8")
                task_registry.set_stream(project_id, "write", number, draft_text)

            task_registry.publish(project_id, "write", number, "draft", {
                "path": result.draft_path,
                "summary": result.summary,
                "entities_tracked": result.entities_tracked,
                "usage": result.usage,
                "text": draft_text,
            })

            if result.enrichment:
                _progress("正在扩充设定集…")
                task_registry.publish(project_id, "write", number, "enrichment", {
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

            if deps.config.generation.auto_consistency_check:
                _progress("正在校验一致性…")
                report = deps.checker.check(number)
                task_registry.publish(project_id, "write", number, "check", {
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

            _progress("完成！")
            task_registry.publish(
                project_id, "write", number, "done", {"chapter": number}
            )
            task_registry.mark_finished(project_id, "write", number)
        except Exception as exc:  # noqa: BLE001
            task_registry.publish(project_id, "write", number, "error", str(exc))
            task_registry.mark_finished(project_id, "write", number, error=str(exc))
        finally:
            def _delayed_cleanup() -> None:
                time.sleep(90)
                t = task_registry.get(project_id, "write", number)
                if t is not None and t.finished:
                    task_registry.unregister(project_id, "write", number)

            threading.Thread(
                target=_delayed_cleanup, name=f"write-cleanup-{number}", daemon=True
            ).start()

    threading.Thread(
        target=_run_write, name=f"write-{project_id}-{number}", daemon=True
    ).start()


@router.post("/write/{number}/start")
def start_write(
    project_id: str, number: int,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Start chapter generation in a background thread (non-blocking).

    Clients should poll ``GET /write-status/{number}`` for ``progress`` and
    ``stream_text``. This avoids long-lived SSE connections that can stall
    other API requests through some reverse proxies.
    """
    started = task_registry.try_start(project_id, "write", number, "准备中…")
    if started:
        _spawn_write_worker(project_id, number, deps)
    t = task_registry.get(project_id, "write", number)
    return {
        "ok": True,
        "started": started,
        "active": t is not None and not t.finished,
        "progress": t.progress if t else "",
        "stream_text": t.stream_text if t else "",
    }


@router.get("/write/{number}")
def write_chapter_sse(
    project_id: str, number: int,
    resume: bool = False,
    deps: ProjectDeps = Depends(get_project_deps),
) -> EventSourceResponse:
    """Optional SSE attach for live tokens (prefer POST /start + write-status)."""
    from queue import Empty

    if not resume:
        started = task_registry.try_start(project_id, "write", number, "准备中…")
        if started:
            _spawn_write_worker(project_id, number, deps)

    sub = task_registry.subscribe(project_id, "write", number)
    if sub is None:
        async def no_job():
            yield sse_event("error", {"message": "没有进行中的生成任务"})
            yield sse_done()
        return EventSourceResponse(no_job(), ping=10)

    event_q, snapshot_text, snapshot_progress, already_finished = sub

    def _emit(kind: str, payload: Any):
        if kind == "__end__":
            return None
        if kind == "progress":
            return sse_progress(str(payload))
        if kind == "token":
            return sse_event("token", {"text": payload})
        if kind == "context":
            return sse_event("context", payload)
        if kind == "draft":
            return sse_event("draft", payload)
        if kind == "enrichment":
            return sse_event("enrichment", payload)
        if kind == "check":
            return sse_event("check", payload)
        if kind == "error":
            return sse_event("error", {"message": payload})
        if kind == "done":
            return sse_done(payload if isinstance(payload, dict) else {"chapter": number})
        return None

    async def event_stream():
        try:
            if snapshot_text:
                yield sse_event("token", {"text": snapshot_text, "replay": True})
            if snapshot_progress:
                yield sse_progress(snapshot_progress)
            if already_finished:
                t = task_registry.get(project_id, "write", number)
                if t is not None and t.error:
                    yield sse_event("error", {"message": t.error})
                yield sse_done({"chapter": number})
                return

            while True:
                try:
                    kind, payload = await asyncio.to_thread(event_q.get, True, 0.25)
                except Empty:
                    t = task_registry.get(project_id, "write", number)
                    if t is None or t.finished:
                        yield sse_done({"chapter": number})
                        return
                    continue

                if kind == "__end__":
                    t = task_registry.get(project_id, "write", number)
                    if t is not None and t.error:
                        yield sse_event("error", {"message": t.error})
                    yield sse_done({"chapter": number})
                    return

                evt = _emit(kind, payload)
                if evt is not None:
                    yield evt
                if kind in ("done", "error"):
                    if kind == "error":
                        yield sse_done()
                    return
        except asyncio.CancelledError:
            return
        finally:
            task_registry.unsubscribe(project_id, "write", number, event_q)

    return EventSourceResponse(
        event_stream(),
        ping=10,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# ---- write status (primary UI update path) ----

@router.get("/write-status/{number}")
def write_status(project_id: str, number: int, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Check if a write/revise is in progress for this chapter."""
    t = task_registry.get(project_id, "write", number) or task_registry.get(project_id, "revise", number)
    if t:
        active = not t.finished
        return {
            "active": active,
            "finished": t.finished,
            "progress": t.progress,
            "stream_text": t.stream_text,
            "error": t.error,
            "started_at": t.started_at,
            "op": t.op,
            "draft_exists": deps.paths.draft_file(number).exists(),
        }
    draft_path = deps.paths.draft_file(number)
    if draft_path.exists():
        return {
            "active": False, "finished": True, "progress": "completed",
            "stream_text": "", "error": None, "draft_exists": True, "op": "",
        }
    return {
        "active": False, "finished": False, "progress": "",
        "stream_text": "", "error": None, "draft_exists": False, "op": "",
    }


# ---- all active tasks ----

@router.get("/tasks")
def list_tasks(project_id: str) -> dict:
    """List all active long-running tasks for this project."""
    tasks = task_registry.list_for_project(project_id)
    return {
        "tasks": [
            {
                "op": t.op,
                "chapter": t.chapter,
                "started_at": t.started_at,
                "progress": t.progress,
                "finished": t.finished,
            }
            for t in tasks
            if not t.finished
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
                # Minimal-fix path: patch only the problematic passages
                # instead of re-writing the whole chapter (preserves voice).
                return deps.writer.apply_minimal_fix(number, text, issues_blob)

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


def _is_runtime_versioned_rel(rel: str) -> bool:
    """Paths that must not leak from live project into a regen fork.

    Matches state/ (entities, threads, reviews), codex/, and story-so-far.
    Excludes volume outlines (planning) and style.md (author-managed).
    """
    rel = rel.replace("\\", "/")
    if rel.startswith("state/") or "/state/" in f"/{rel}":
        return True
    if rel.startswith("codex/") or "/codex/" in f"/{rel}":
        return True
    if rel == "outline/story_so_far.md":
        return True
    return False


def _is_draft_ge(rel_path: str, number: int) -> bool:
    """Return True if *rel_path* is a draft for chapter >= *number*.

    >>> _is_draft_ge("drafts/ch002.md", 1)
    True
    >>> _is_draft_ge("drafts/ch001.md", 2)
    False
    >>> _is_draft_ge("codex/characters/foo.md", 1)
    False
    """
    # Normalised separator is "/" from the caller.
    parts = rel_path.split("/")
    if len(parts) >= 2 and parts[0] == "drafts":
        fn = parts[-1]
        m = re.match(r"ch0*(\d+)", fn)
        if m:
            return int(m.group(1)) >= number
    return False


def _clean_codex_post_chapter(deps: ProjectDeps, number: int) -> None:
    """Strip revelations, contradictions, and body fragments added
    by chapters >= *number* from every codex entry.

    If a codex entry has NO remaining content (all revelations, contradictions,
    and body fragments were from chapters >= *number*), delete the file entirely
    — it was created by chapters that are being rolled back.
    """
    import yaml as _yaml

    codex_dir = deps.paths.codex_dir
    if not codex_dir.exists():
        return
    for md_file in codex_dir.rglob("*.md"):
        if md_file.name.startswith("."):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        parts = text.split("---\n", 2)
        if len(parts) < 3:
            continue
        front_str = parts[1]
        body = parts[2]

        try:
            front = _yaml.safe_load(front_str)
        except _yaml.YAMLError:
            continue
        if not isinstance(front, dict):
            continue

        modified = False

        # Filter revelations.
        revs = front.get("revelations") or []
        kept_revs = [
            r for r in revs
            if isinstance(r, dict) and r.get("chapter", 0) < number
        ]
        if len(kept_revs) != len(revs):
            front["revelations"] = kept_revs
            modified = True

        # Filter contradictions.
        conts = front.get("contradictions") or []
        kept_conts = [
            c for c in conts
            if isinstance(c, dict) and c.get("chapter", 0) < number
        ]
        if len(kept_conts) != len(conts):
            front["contradictions"] = kept_conts
            modified = True

        # Strip body fragments tagged with chapter >= N.
        # Use span-based deletion to avoid str.replace deleting wrong content.
        if body:
            import re as _re
            pattern = _re.compile(
                r"(\n\n)?🤖\s*第\s*(\d+)\s*章.*?(?=\n\n🤖|\n*$)",
                _re.DOTALL,
            )
            # Collect spans to delete (in reverse order for safe splicing).
            spans_to_delete: list[tuple[int, int]] = []
            for m in pattern.finditer(body):
                if int(m.group(2)) >= number:
                    spans_to_delete.append((m.start(), m.end()))
            if spans_to_delete:
                # Build new body by splicing out the deleted spans.
                new_body_parts: list[str] = []
                last_end = 0
                for start, end in spans_to_delete:
                    new_body_parts.append(body[last_end:start])
                    last_end = end
                new_body_parts.append(body[last_end:])
                body = "".join(new_body_parts)
                body = _re.sub(r"\n{3,}", "\n\n", body).strip()
                modified = True

        # Check if this entry is now empty (all content was from >= N chapters).
        has_revs = bool(front.get("revelations"))
        has_conts = bool(front.get("contradictions"))
        has_body = bool(body and body.strip())
        if modified and not has_revs and not has_conts and not has_body:
            # Entire entry was created by chapters >= N; delete the file.
            try:
                md_file.unlink()
            except Exception:
                pass
            continue

        if modified:
            new_front = _yaml.dump(front, allow_unicode=True, sort_keys=False).strip()
            md_file.write_text(
                f"---\n{new_front}\n---\n{body}\n",
                encoding="utf-8",
            )


def _clean_entity_state_post_chapter(deps: ProjectDeps, number: int) -> None:
    """Strip knowledge / possessions added by chapters >= *number*
    and revert last_seen_chapter.

    If an entity state file becomes empty (no knowledge, no possessions, and
    last_seen_chapter was >= N), delete the file entirely — this entity was
    first introduced in a chapter that is being rolled back.
    """
    import yaml as _yaml

    state_dir = deps.paths.state_dir / "entities"
    if not state_dir.exists():
        return
    for yf in state_dir.glob("*.yaml"):
        if yf.name.startswith("."):
            continue
        try:
            state = _yaml.safe_load(yf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(state, dict):
            continue
        modified = False

        # Filter knowledge.
        knowledge = state.get("knowledge") or []
        if isinstance(knowledge, list):
            filtered = [
                k for k in knowledge
                if isinstance(k, dict) and k.get("since_chapter", 0) < number
            ]
            if len(filtered) != len(knowledge):
                state["knowledge"] = filtered
                modified = True

        # Filter possessions.
        possessions = state.get("possessions") or []
        if isinstance(possessions, list):
            filtered = [
                p for p in possessions
                if isinstance(p, dict) and p.get("since_chapter", 0) < number
            ]
            if len(filtered) != len(possessions):
                state["possessions"] = filtered
                modified = True

        # Revert last_seen_chapter.
        lsc = state.get("last_seen_chapter", 0)
        if isinstance(lsc, int) and lsc >= number:
            state["last_seen_chapter"] = max(0, number - 1)
            modified = True

        if modified:
            # Check if state is now empty (entity was created in a chapter >= N).
            has_knowledge = bool(state.get("knowledge"))
            has_possessions = bool(state.get("possessions"))
            lsc_now = state.get("last_seen_chapter", 0)
            if not has_knowledge and not has_possessions and (
                not isinstance(lsc_now, int) or lsc_now == 0
            ):
                # Entity state is empty; delete the file.
                try:
                    yf.unlink()
                except Exception:
                    pass
                continue

            yf.write_text(
                _yaml.dump(state, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
