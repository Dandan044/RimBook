"""Prompt-template workflow routes — catalog, edit, preview.

These routes let the frontend ``/workflow`` page observe every prompt that feeds
the LLM pipeline, edit individual templates (workspace-level overrides persisted
in ``<workspace>/prompts.yaml``), reset overrides, and render a preview of one
template filled with the real data for a chosen chapter.

Catalog/override routes are *not* scoped to a project (prompts are workspace-
level). The preview route is project-scoped because it reads chapter/outline/
codex from a specific project.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from rimbook.llm import PROMPT_KEYS, render_preview

from ..deps import ProjectDeps, get_project_deps, workspace_root

# Workspace-level routes (no project_id in URL).
router = APIRouter(prefix="/api/prompts", tags=["prompts"])

# Project-scoped preview route lives on a separate router below.


def _workspace() -> Path:
    env = os.environ.get("RIMBOOK_WORKSPACE")
    return Path(env).resolve() if env else Path.cwd()


# ---- request models ----


class PromptUpdate(BaseModel):
    value: str


class PromptPreviewRequest(BaseModel):
    number: int = 1
    premise: str = ""
    instructions: str = ""


# ---- catalog ----


def _entry(key: str) -> dict:
    from rimbook.llm import catalog

    items = {p["key"]: p for p in catalog(_workspace())}
    if key not in items:
        raise HTTPException(404, f"Unknown prompt key '{key}'")
    return items[key]


@router.get("")
def list_prompts() -> dict:
    """Return the full catalog of prompts with current (effective) values."""
    from rimbook.llm import catalog

    items = catalog(_workspace())
    stages_order = ["planning", "writing", "summarization", "checking", "enrichment"]
    seen = [p["stage"] for p in items]
    stages = [s for s in stages_order if s in seen] + [
        s for s in dict.fromkeys(seen) if s not in stages_order
    ]
    return {"prompts": items, "stages": stages}


@router.put("/{key}")
def update_prompt(key: str, req: PromptUpdate) -> dict:
    """Set or replace a workspace-level override for one prompt template."""
    if key not in PROMPT_KEYS:
        raise HTTPException(404, f"Unknown prompt key '{key}'")
    from rimbook.llm import list_overrides, save_prompts_overrides

    ws = _workspace()
    overrides = list_overrides(ws)
    overrides[key] = req.value
    save_prompts_overrides(ws, overrides)
    return _entry(key)


@router.delete("/{key}")
def reset_prompt(key: str) -> dict:
    """Delete the override for *key* (reverts to the in-code default)."""
    if key not in PROMPT_KEYS:
        raise HTTPException(404, f"Unknown prompt key '{key}'")
    from rimbook.llm import list_overrides, save_prompts_overrides

    ws = _workspace()
    overrides = list_overrides(ws)
    if key in overrides:
        overrides.pop(key, None)
        save_prompts_overrides(ws, overrides)
    return _entry(key)


@router.post("/reset")
def reset_all_prompts() -> dict:
    """Clear all workspace-level prompt overrides."""
    from rimbook.llm import reset_all_overrides

    reset_all_overrides(_workspace())
    return {"ok": True}


# ---- project-scoped preview ----


preview_router = APIRouter(prefix="/api/projects/{project_id}/prompts", tags=["prompts"])


@preview_router.get("/{key}/preview")
def preview_prompt(
    key: str,
    number: int = 1,
    premise: str = "",
    instructions: str = "",
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Render one prompt template with real data for chapter *number*.

    Pass ?premise= for synopsis_user, ?instructions= for writer_revise_user.
    """
    if key not in PROMPT_KEYS:
        raise HTTPException(404, f"Unknown prompt key '{key}'")
    try:
        rendered = render_preview(
            deps.prompts,
            key,
            outline=deps.outline,
            assembler=deps.assembler,
            codex=deps.codex,
            paths=deps.paths,
            number=number,
            premise=premise or "",
            instructions=instructions or "",
        )
    except KeyError:
        raise HTTPException(404, f"Unknown prompt key '{key}'")
    return {"rendered": rendered}