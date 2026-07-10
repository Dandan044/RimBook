"""Web dependency injection — adapts the CLI's Deps pattern for FastAPI.

Each request that targets a specific project gets a fully-wired :class:`ProjectDeps`
injected via ``Depends(get_project_deps)``. The project is identified by its
directory name (the ``project_id`` path parameter), resolved relative to a
configurable workspace root.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException

from rimbook.config import Config, GenerationConfig, load_config
from rimbook.codex import CodexEntry, CodexStore
from rimbook.llm import LLMClient, Prompts
from rimbook.memory import (
    ContextAssembler,
    EntityStateStore,
    SlidingWindow,
    Summarizer,
)
from rimbook.outline import OutlineStore
from rimbook.pipeline import Checker, Planner, Writer, PostWritePipeline
from rimbook.project import ProjectPaths, scaffold_project

PROMPTS = Prompts()


def workspace_root() -> Path:
    """Root directory that contains all novel projects.

    Defaults to the current working directory; override with
    ``RIMBOOK_WORKSPACE`` env var.
    """
    env = os.environ.get("RIMBOOK_WORKSPACE")
    return Path(env).resolve() if env else Path.cwd()


class ProjectDeps:
    """Fully-wired component bundle for one project (like CLI's Deps)."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.config = load_config(project_dir)
        self.paths = ProjectPaths(root=project_dir)
        self._llm: LLMClient | None = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.config.llm)
        return self._llm

    @property
    def codex(self) -> CodexStore:
        return CodexStore(self.paths)

    @property
    def outline(self) -> OutlineStore:
        return OutlineStore(self.paths)

    @property
    def entity_state(self) -> EntityStateStore:
        return EntityStateStore(self.paths)

    @property
    def window(self) -> SlidingWindow:
        return SlidingWindow(self.paths)

    @property
    def assembler(self) -> ContextAssembler:
        return ContextAssembler(
            self.paths,
            codex=self.codex,
            outline=self.outline,
            entity_state=self.entity_state,
            window=self.window,
            generation=self.config.generation,
        )

    @property
    def summarizer(self) -> Summarizer:
        return Summarizer(self.llm, PROMPTS, self.outline)

    @property
    def writer(self) -> Writer:
        return Writer(
            self.paths,
            llm=self.llm,
            prompts=PROMPTS,
            outline=self.outline,
            assembler=self.assembler,
            summarizer=self.summarizer,
            entity_state=self.entity_state,
            codex=self.codex,
            generation=self.config.generation,
        )

    @property
    def planner(self) -> Planner:
        return Planner(self.llm, PROMPTS, self.outline)

    @property
    def checker(self) -> Checker:
        return Checker(self.paths, llm=self.llm, prompts=PROMPTS)

    @property
    def enricher(self) -> PostWritePipeline:
        return PostWritePipeline(
            llm=self.llm,
            prompts=PROMPTS,
            codex=self.codex,
            entity_state=self.entity_state,
            summarizer=self.summarizer,
            generation=self.config.generation,
        )


def _resolve_project(project_id: str) -> Path:
    """Resolve a project_id to an absolute directory under the workspace."""
    root = workspace_root()
    # project_id may be a relative name or an absolute path.
    candidate = (root / project_id).resolve()
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    if not (candidate / "config.yaml").exists():
        raise HTTPException(status_code=404, detail=f"'{project_id}' is not a RimBook project")
    return candidate


def get_project_deps(project_id: str) -> ProjectDeps:
    """FastAPI dependency: resolve project_id → ProjectDeps."""
    return ProjectDeps(_resolve_project(project_id))
