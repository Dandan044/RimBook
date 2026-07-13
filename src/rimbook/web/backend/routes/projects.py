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

# Mask sentinel — used to detect masked keys that must NOT be written back.
_MASK_FILL = "***"


def _mask_key(raw: str) -> str:
    """Return an ASCII-safe masked representation of an API key.

    The result uses only ASCII characters so it can never cause encoding
    errors, and it contains the sentinel ``***`` so ``_is_masked`` can
    detect it and prevent overwriting the real key on save.
    """
    if not raw or raw == "rimbook-no-key" or raw.startswith("${"):
        return ""
    if len(raw) <= 12:
        return _MASK_FILL
    return raw[:6] + _MASK_FILL + raw[-4:]


def _is_masked(value: str | None) -> bool:
    """Return True if *value* looks like a masked/placeholder key."""
    if not value:
        return False
    return _MASK_FILL in value or "\u2026" in value


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
    # Embedding fields
    embed_base_url: str | None = None
    embed_api_key: str | None = None
    embed_model: str | None = None
    # Generation fields
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    recent_window_chapters: int | None = None
    summary_history: int | None = None
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
    # Project config only holds per-project fields; LLM settings are global.
    config: dict[str, Any] = {
        "title": req.title,
        "author": req.author,
        "language": req.language,
        "generation": {
            "temperature": 0.85,
            "max_tokens": 40000,
            "recent_window_chapters": 1,
            "summary_history": 6,
            "auto_consistency_check": True,
            "auto_fix": False,
            "max_fix_rounds": 2,
            "auto_checkpoint": True,
            "max_checkpoints": 50,
        },
    }
    (target / "config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return ProjectInfo(id=req.name, title=req.title, author=req.author,
                       language=req.language, path=str(target))


@router.get("/{project_id}/config")
def get_config(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Read project configuration."""
    cfg = deps.config
    # Return api_key masked for security.
    # Use ASCII-safe mask characters so the masked value can never be
    # confused with a real key and will be rejected by update_config.
    raw_key = cfg.llm.api_key or ""
    masked_key = _mask_key(raw_key)
    emb_key = cfg.llm.embedding.api_key or ""
    masked_emb_key = _mask_key(emb_key)
    # Show the embedding base_url after stripping any /embeddings suffix,
    # so the user sees the clean base URL that the SDK actually uses.
    emb_base_url = cfg.llm.embedding.resolved_base_url(cfg.llm.base_url)
    return {
        "title": cfg.title,
        "author": cfg.author,
        "language": cfg.language,
        "llm": {
            "base_url": cfg.llm.base_url,
            "api_key": masked_key,
            "model": cfg.llm.model,
            "check_model": cfg.llm.effective_check_model,
            "embedding": {
                "base_url": emb_base_url,
                "api_key": masked_emb_key or masked_key,
                "model": cfg.llm.embedding.model,
            },
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
            # Never overwrite a real API key with a masked placeholder.
            if key == "api_key" and _is_masked(val):
                continue
            llm[key] = val
    # Embedding (nested under llm)
    emb = llm.setdefault("embedding", {})
    if req.embed_base_url is not None:
        # Strip /embeddings suffix — the OpenAI SDK appends it automatically.
        url = req.embed_base_url.rstrip("/")
        if url.endswith("/embeddings"):
            url = url[: -len("/embeddings")]
        emb["base_url"] = url
    if req.embed_api_key is not None:
        if not _is_masked(req.embed_api_key):
            emb["api_key"] = req.embed_api_key
    if req.embed_model is not None:
        emb["model"] = req.embed_model
    # Generation
    gen = raw.setdefault("generation", {})
    for key in ("temperature", "max_tokens", "top_p", "recent_window_chapters",
                "summary_history", "auto_consistency_check", "auto_fix", "max_fix_rounds"):
        val = getattr(req, key, None)
        if val is not None:
            gen[key] = val
    cfg_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True}


@router.delete("/{project_id}")
def delete_project(project_id: str) -> dict:
    """Delete an entire project directory (irreversible).

    Safety checks:
      * Only directories under the workspace root are deletable.
      * The directory must contain a ``config.yaml`` (must be a RimBook project).
    """
    import shutil
    root = workspace_root()
    target = (root / project_id).resolve()
    # Prevent path-traversal: target must be under workspace root.
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status_code=403, detail="Cannot delete projects outside the workspace")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    if not (target / "config.yaml").exists():
        raise HTTPException(status_code=404, detail=f"'{project_id}' is not a RimBook project")
    shutil.rmtree(target)
    return {"ok": True, "deleted": project_id}


@router.post("/{project_id}/test-llm")
def test_llm(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Test LLM chat-completion connectivity with a tiny request."""
    try:
        result = deps.llm.generate(
            [{"role": "user", "content": "Hi, reply with just 'ok'."}],
            max_tokens=10,
            temperature=0.0,
        )
        return {
            "ok": True,
            "model": result.model,
            "reply": result.content.strip()[:100],
            "usage": result.usage,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/{project_id}/test-embedding")
def test_embedding(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Test embedding endpoint connectivity."""
    try:
        vectors = deps.llm.embed("test connectivity")
        dims = len(vectors[0]) if vectors else 0
        return {"ok": True, "model": deps.llm.embedding_model, "dimensions": dims}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
