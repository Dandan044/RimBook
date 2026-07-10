"""Codex (Story Bible) management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from rimbook.codex import CodexEntry, CodexStore
from rimbook.codex.models import VALID_TYPES

from ..deps import ProjectDeps, get_project_deps

router = APIRouter(prefix="/api/projects/{project_id}/codex", tags=["codex"])


# ---- request / response models ----

class CodexEntryIn(BaseModel):
    id: str
    name: str
    type: str
    aliases: list[str] = []
    tags: list[str] = []
    related: list[str] = []
    body: str = ""


class CodexEntryOut(BaseModel):
    id: str
    name: str
    type: str
    aliases: list[str] = []
    tags: list[str] = []
    related: list[str] = []
    body: str = ""
    # v2 structured fields
    revelations: list[dict] = []
    contradictions: list[dict] = []
    relationships: list[dict] = []


class CodexEntryUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None
    related: list[str] | None = None
    body: str | None = None


# ---- routes ----

@router.get("", response_model=list[CodexEntryOut])
def list_codex(
    type: str | None = None,
    deps: ProjectDeps = Depends(get_project_deps),
) -> list[CodexEntryOut]:
    """List codex entries, optionally filtered by type."""
    entries = deps.codex.list_by_type(type) if type else deps.codex.all()
    return [_entry_to_out(e) for e in entries]


@router.post("", response_model=CodexEntryOut, status_code=201)
def add_codex(req: CodexEntryIn, deps: ProjectDeps = Depends(get_project_deps)) -> CodexEntryOut:
    """Add a new codex entry."""
    if req.type not in VALID_TYPES:
        raise HTTPException(400, f"Invalid type '{req.type}'; expected one of {VALID_TYPES}")
    try:
        existing = deps.codex.read(req.id)
        raise HTTPException(409, f"Entry '{req.id}' already exists")
    except FileNotFoundError:
        pass
    entry = CodexEntry(
        id=req.id, name=req.name, type=req.type,
        aliases=req.aliases, tags=req.tags, related=req.related, body=req.body,
    )
    deps.codex.write(entry)
    return _entry_to_out(entry)


@router.get("/{entry_id}", response_model=CodexEntryOut)
def get_codex(entry_id: str, deps: ProjectDeps = Depends(get_project_deps)) -> CodexEntryOut:
    """Get a single codex entry by id."""
    try:
        entry = deps.codex.read(entry_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Entry '{entry_id}' not found")
    return _entry_to_out(entry)


@router.put("/{entry_id}", response_model=CodexEntryOut)
def update_codex(
    entry_id: str, req: CodexEntryUpdate, deps: ProjectDeps = Depends(get_project_deps)
) -> CodexEntryOut:
    """Update a codex entry (partial)."""
    try:
        entry = deps.codex.read(entry_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Entry '{entry_id}' not found")
    # Apply partial updates.
    if req.name is not None:
        entry.name = req.name
    if req.type is not None:
        if req.type not in VALID_TYPES:
            raise HTTPException(400, f"Invalid type '{req.type}'")
        entry.type = req.type
    if req.aliases is not None:
        entry.aliases = req.aliases
    if req.tags is not None:
        entry.tags = req.tags
    if req.related is not None:
        entry.related = req.related
    if req.body is not None:
        entry.body = req.body
    deps.codex.write(entry)
    return _entry_to_out(entry)


@router.delete("/{entry_id}")
def delete_codex(entry_id: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Delete a codex entry."""
    ok = deps.codex.delete(entry_id)
    if not ok:
        raise HTTPException(404, f"Entry '{entry_id}' not found")
    return {"ok": True}


def _entry_to_out(e: CodexEntry) -> CodexEntryOut:
    return CodexEntryOut(
        id=e.id, name=e.name, type=e.type,
        aliases=e.aliases, tags=e.tags, related=e.related, body=e.body,
        revelations=[r.model_dump() for r in e.revelations],
        contradictions=[c.model_dump() for c in e.contradictions],
        relationships=[r.model_dump() for r in e.relationships],
    )
