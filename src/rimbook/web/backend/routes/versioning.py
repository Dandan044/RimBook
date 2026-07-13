"""Checkpoint & branch management routes."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import ProjectDeps, get_project_deps

router = APIRouter(prefix="/api/projects/{project_id}", tags=["versioning"])

# ── request models ──────────────────────────────────────────────────

class CreateCheckpointReq(BaseModel):
    label: str = "manual"
    files: list[str] = []

class CreateBranchReq(BaseModel):
    name: str
    from_checkpoint: str | None = None

class RestoreReq(BaseModel):
    files: list[str] | None = None

# ── branches ────────────────────────────────────────────────────────

@router.get("/branches")
def list_branches(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    branches = vm.list_branches()
    fork_points = vm.get_fork_points()
    return {
        "branches": [b.to_dict() for b in branches],
        "current": vm.get_current_branch(),
        "fork_points": fork_points,
    }

@router.post("/branches")
def create_branch(req: CreateBranchReq, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    try:
        name = vm.create_branch(req.name, req.from_checkpoint)
        return {"ok": True, "branch": name}
    except ValueError as e:
        raise HTTPException(409, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

@router.post("/branches/{name}/switch")
def switch_branch(name: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    try:
        saved = vm.switch_branch(name)
        return {"ok": True, "branch": name, "saved_checkpoint": saved or None}
    except ValueError as e:
        raise HTTPException(404, str(e))

@router.delete("/branches/{name}")
def delete_branch(name: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    try:
        vm.delete_branch(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.get("/branches/{name}/history")
def branch_history(name: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    history = vm.get_branch_history(name)
    fork_points = vm.get_fork_points()
    return {
        "branch": name,
        "history": [h.to_dict() for h in history],
        "fork_points": {
            k: v for k, v in fork_points.items()
            if k in {h.name for h in history}
        },
    }

# ── checkpoints ─────────────────────────────────────────────────────

@router.get("/checkpoints")
def list_checkpoints(
    branch: str | None = None, deps: ProjectDeps = Depends(get_project_deps)
) -> dict:
    vm = deps.version_manager
    if branch:
        checkpoints = vm.list_checkpoints(branch=branch)
    else:
        checkpoints = vm.list_all_checkpoints()
    fork_points = vm.get_fork_points()
    return {
        "checkpoints": [c.to_dict() for c in checkpoints],
        "current_branch": vm.get_current_branch(),
        "fork_points": fork_points,
    }

@router.post("/checkpoints")
def create_checkpoint(req: CreateCheckpointReq, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    if not req.files:
        # Full snapshot.
        ts = time.strftime("%Y%m%d-%H%M%S")
        snap_dir = deps.paths.versions_dir / f"{ts}-{req.label}"
        i = 1
        while snap_dir.exists():
            snap_dir = deps.paths.versions_dir / f"{ts}-{req.label}-{i}"
            i += 1
        snap_dir.mkdir(parents=True)
        copied = 0
        for item in deps.project_dir.iterdir():
            if item.name == ".versions":
                continue
            if item.is_dir():
                shutil.copytree(item, snap_dir / item.name, dirs_exist_ok=True)
                copied += sum(1 for _ in (snap_dir / item.name).rglob("*") if _.is_file())
            else:
                shutil.copy2(item, snap_dir / item.name)
                copied += 1
        # Write manifest.
        branch = vm.get_current_branch()
        import json as _json
        branches = vm._read_branches()
        parent = branches.get(branch)
        manifest = snap_dir / ".manifest"
        manifest.write_text(
            f"label: {req.label}\n"
            f"timestamp: {ts}\n"
            f"branch: {branch}\n"
            f"parent: {parent or ''}\n"
            f"files: {copied}\n",
            encoding="utf-8",
        )
        # Advance branch pointer.
        branches[branch] = snap_dir.name
        vm._write_branches(branches)
        vm._append_journal({"op": "checkpoint", "checkpoint": snap_dir.name, "label": req.label, "branch": branch, "files": copied})
        return {"checkpoint": snap_dir.name, "files": copied, "branch": branch}
    # Incremental.
    file_paths = [deps.project_dir / f for f in req.files]
    name = vm.create_checkpoint(req.label, file_paths)
    cps = vm.list_checkpoints()
    fc = cps[0].file_count if cps else 0
    return {"checkpoint": name, "files": fc, "branch": vm.get_current_branch()}

@router.post("/checkpoints/{name}/restore")
def restore_checkpoint(name: str, req: RestoreReq, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    try:
        file_paths = None
        if req.files is not None:
            file_paths = [deps.project_dir / f for f in req.files]
        result = vm.restore_checkpoint(name, file_paths)
        return {"restored": result["restored"], "skipped": result["skipped"]}
    except FileNotFoundError:
        raise HTTPException(404, f"Checkpoint '{name}' not found")

@router.get("/checkpoints/{name}/diff")
def diff_checkpoint(name: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    snap_dir = deps.paths.versions_dir / name
    if not snap_dir.exists():
        raise HTTPException(404, f"Checkpoint '{name}' not found")
    changed: list[dict] = []
    added: list[str] = []
    for item in snap_dir.rglob("*"):
        if item.is_file() and item.name == ".manifest":
            continue
        rel = str(item.relative_to(snap_dir))
        current = deps.project_dir / rel
        if not current.exists():
            changed.append({"file": rel, "status": "removed_in_current"})
        elif current.read_bytes() != item.read_bytes():
            changed.append({"file": rel, "status": "modified"})
    for item in deps.project_dir.rglob("*"):
        if item.is_file() and ".versions" not in str(item):
            rel = str(item.relative_to(deps.project_dir))
            if not (snap_dir / rel).exists():
                added.append(rel)
    return {"changed": changed, "added": added}

@router.delete("/checkpoints/{name}")
def delete_checkpoint(name: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    vm = deps.version_manager
    try:
        vm.delete_checkpoint(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
