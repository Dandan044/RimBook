"""RimBook Web — FastAPI application.

Run with:  python -m rimbook.web  (or  uvicorn rimbook.web.app:app --reload)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
from pathlib import Path

from .routes import codex, llm_logs, narrative, outline, projects, prompts, server, status, versioning, writer

app = FastAPI(
    title="RimBook",
    version="0.1.0",
    description="LLM-powered long-form fiction writing workbench",
)

# CORS — allow the Vite dev server (localhost:5173) and same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes.
app.include_router(projects.router)
app.include_router(status.router)
app.include_router(codex.router)
app.include_router(outline.router)
app.include_router(writer.router)
app.include_router(narrative.router)
app.include_router(prompts.router)
app.include_router(prompts.preview_router)
app.include_router(server.router)
app.include_router(versioning.router)
app.include_router(llm_logs.router)

# ---------------------------------------------------------------------------
# Global workspace config routes (not tied to any project)
# ---------------------------------------------------------------------------
_MASK_FILL = "***"


def _mask_key(raw: str) -> str:
    if not raw or raw == "rimbook-no-key" or raw.startswith("${"):
        return raw or ""
    if len(raw) <= 12:
        return _MASK_FILL
    return raw[:6] + _MASK_FILL + raw[-4:]


def _is_masked(value: str | None) -> bool:
    if not value:
        return False
    return _MASK_FILL in value or "\u2026" in value


def _workspace_root() -> Path:
    env = os.environ.get("RIMBOOK_WORKSPACE")
    return Path(env).resolve() if env else Path.cwd()


@app.get("/api/config")
def get_global_config() -> dict:
    """Read the global workspace config (LLM + embedding). Shared by all projects."""
    from rimbook.config import load_global_config

    gc = load_global_config(_workspace_root())
    llm = gc.get("llm", {}) if isinstance(gc, dict) else {}
    emb = llm.get("embedding", {}) if isinstance(llm, dict) else {}
    raw_key = str(llm.get("api_key") or "") if isinstance(llm, dict) else ""
    masked_key = _mask_key(raw_key) if not raw_key.startswith("${") else raw_key
    emb_key = str(emb.get("api_key") or "") if isinstance(emb, dict) else ""
    masked_emb_key = _mask_key(emb_key) if not emb_key.startswith("${") else emb_key
    return {
        "llm": {
            "base_url": llm.get("base_url", "https://api.openai.com/v1") if isinstance(llm, dict) else "https://api.openai.com/v1",
            "api_key": masked_key,
            "model": llm.get("model", "gpt-4o") if isinstance(llm, dict) else "gpt-4o",
            "check_model": llm.get("check_model") if isinstance(llm, dict) else None,
            "reasoning_effort": llm.get("reasoning_effort") if isinstance(llm, dict) else None,
            "embedding": {
                "base_url": emb.get("base_url") if isinstance(emb, dict) else None,
                "api_key": masked_emb_key,
                "model": emb.get("model", "text-embedding-3-small") if isinstance(emb, dict) else "text-embedding-3-small",
            },
        },
    }


class GlobalConfigUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    check_model: str | None = None
    reasoning_effort: str | None = None
    embed_base_url: str | None = None
    embed_api_key: str | None = None
    embed_model: str | None = None


@app.put("/api/config")
def update_global_config(req: GlobalConfigUpdate) -> dict:
    """Update the global workspace config (LLM + embedding)."""
    from rimbook.config import load_global_config, save_global_config

    gc = load_global_config(_workspace_root())
    llm = gc.setdefault("llm", {})
    emb = llm.setdefault("embedding", {})

    for key in ("base_url", "api_key", "model", "check_model"):
        val = getattr(req, key, None)
        if val is not None:
            if key == "api_key" and _is_masked(val):
                continue
            llm[key] = val

    # reasoning_effort: distinguish "not sent" vs "explicitly null/empty" (turn off).
    # Pydantic maps both omitted and JSON-null to None; use model_fields_set.
    if "reasoning_effort" in req.model_fields_set:
        llm["reasoning_effort"] = req.reasoning_effort or None

    if req.embed_base_url is not None:
        url = req.embed_base_url.rstrip("/")
        if url.endswith("/embeddings"):
            url = url[: -len("/embeddings")]
        emb["base_url"] = url
    if req.embed_api_key is not None:
        if not _is_masked(req.embed_api_key):
            emb["api_key"] = req.embed_api_key
    if req.embed_model is not None:
        emb["model"] = req.embed_model

    save_global_config(gc, _workspace_root())
    return {"ok": True}

# Serve built Vue frontend as static files (production mode).
# The frontend build output goes to web/backend/static/.
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists() and any(_static_dir.iterdir()):
    # Mount static assets (js, css, etc.) at /assets
    app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="static-assets")

    # SPA catch-all: serve index.html for any non-API route so Vue Router
    # can handle client-side routing.
    from fastapi.responses import FileResponse

    # index.html must not be cached — otherwise a rebuilt SPA (new menu items,
    # new hashed bundles) stays invisible until a hard refresh.
    _HTML_NO_CACHE = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """Serve index.html for all non-API routes (SPA client-side routing)."""
        # If the path matches an actual static file, serve it directly.
        file_path = _static_dir / path
        if file_path.is_file():
            headers = _HTML_NO_CACHE if file_path.suffix.lower() in {".html", ".htm"} else None
            return FileResponse(str(file_path), headers=headers)
        # Otherwise serve index.html for Vue Router to handle.
        return FileResponse(str(_static_dir / "index.html"), headers=_HTML_NO_CACHE)


def main():
    """CLI entry point: ``rimbook-web`` or ``python -m rimbook.web``."""
    import socket
    import sys
    import time
    import uvicorn
    from rimbook.web.launcher import _write_pid, _delete_pid_files

    host = os.environ.get("RIMBOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("RIMBOOK_PORT", "8000"))

    # Support bind-retry for seamless restart (the old process may not have
    # released the port yet).  Set via RIMBOOK_BIND_RETRY env var.
    max_retries = int(os.environ.get("RIMBOOK_BIND_RETRY", "0"))
    for attempt in range(max_retries + 1):
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
            probe.close()
            break  # port free — proceed
        except OSError:
            if attempt < max_retries:
                time.sleep(1)
            # else: last attempt, let uvicorn report the error naturally

    # Persist PID + port so the launcher / frontend can query status.
    _write_pid(os.getpid(), port)

    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        _delete_pid_files()
