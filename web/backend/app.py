"""RimBook Web — FastAPI application.

Run with:  python -m rimbook.web  (or  uvicorn rimbook.web.app:app --reload)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import codex, outline, projects, status, writer

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

# Serve built Vue frontend as static files (production mode).
# The frontend build output goes to web/backend/static/.
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists() and any(_static_dir.iterdir()):
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="spa")


def main():
    """CLI entry point: ``rimbook-web`` or ``python -m rimbook.web``."""
    import uvicorn
    host = os.environ.get("RIMBOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("RIMBOOK_PORT", "8000"))
    uvicorn.run("rimbook.web.app:app", host=host, port=port, reload=True)
