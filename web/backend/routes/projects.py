"""Project management routes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from rimbook.config import load_config
from rimbook.project import scaffold_project

from ..deps import ProjectDeps, get_project_deps, workspace_root

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ---- request / response models ----

class ProjectCreate(BaseModel):
    name: str = Field(..., description="Project directory name")
    title: str = "Untitled Novel"
    author: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    check_model: str | None = None
    language: str = "zh"


class ProjectInfo(BaseModel):
    id: str
    title: str
    author: str
    language: str
    path: str


class ConfigUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    language: str | None = None
    # LLM fields
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    check_model: str | None = None
    # Generation fields
    temperature: float | None = None
    max_tokens: int | None = None
    auto_consistency_check: bool | None = None
    auto_fix: bool | None = None
    max_fix_rounds: int | None = None


# ---- routes ----

@router.get("", response_model=list[ProjectInfo])
def list_projects() -> list[ProjectInfo]:
    """List all RimBook projects under the workspace root."""
    root = workspace_root()
    out: list[ProjectInfo] = []
    if not root.exists():
        return out
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        cfg_path = child / "config.yaml"
        if not cfg_path.exists():
            continue
        try:
            cfg = load_config(child)
        except Exception:
            continue
        out.append(ProjectInfo(
            id=child.name,
            title=cfg.title,
            author=cfg.author,
            language=cfg.language,
            path=str(child),
        ))
    return out


@router.post("", response_model=ProjectInfo, status_code=201)
def create_project(req: ProjectCreate) -> ProjectInfo:
    """Create a new RimBook project."""
    root = workspace_root()
    target = (root / req.name).resolve()
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Directory '{req.name}' already exists")
    import yaml
    paths = scaffold_project(target)
    config: dict[str, Any] = {
        "title": req.title,
        "author": req.author,
        "language": req.language,
        "llm": {
            "base_url": req.base_url,
            "api_key": "${LLM_API_KEY}",
            "model": req.model,
            "embedding": {"base_url": req.base_url, "model": "text-embedding-3-small"},
        },
        "generation": {
            "temperature": 0.85,
            "max_tokens": 4000,
            "recent_window_chapters": 1,
            "summary_history": 6,
            "auto_consistency_check": True,
            "auto_fix": False,
            "max_fix_rounds": 2,
        },
    }
    if req.check_model:
        config["llm"]["check_model"] = req.check_model
    (target / "config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return ProjectInfo(id=req.name, title=req.title, author=req.author,
                       language=req.language, path=str(target))


@router.get("/{project_id}/config")
def get_config(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Read project configuration."""
    cfg = deps.config
    return {
        "title": cfg.title,
        "author": cfg.author,
        "language": cfg.language,
        "llm": {
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "check_model": cfg.llm.effective_check_model,
            "embedding": {"model": cfg.llm.embedding.model},
        },
        "generation": cfg.generation.model_dump(),
    }


@router.put("/{project_id}/config")
def update_config(req: ConfigUpdate, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Update project configuration (partial)."""
    import yaml
    cfg_path = deps.paths.config_file
    raw: dict = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    # Top-level
    for key in ("title", "author", "language"):
        val = getattr(req, key, None)
        if val is not None:
            raw[key] = val
    # LLM
    llm = raw.setdefault("llm", {})
    for key in ("base_url", "api_key", "model", "check_model"):
        val = getattr(req, key, None)
        if val is not None:
            llm[key] = val
    # Generation
    gen = raw.setdefault("generation", {})
    for key in ("temperature", "max_tokens", "auto_consistency_check", "auto_fix", "max_fix_rounds"):
        val = getattr(req, key, None)
        if val is not None:
            gen[key] = val
    cfg_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True}
