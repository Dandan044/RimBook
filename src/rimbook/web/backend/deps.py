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
from rimbook.llm import LLMClient, Prompts, load_prompts
from rimbook.llm.trace import TraceStore
from rimbook.memory import (
    ContextAssembler,
    EntityStateStore,
    SlidingWindow,
    Summarizer,
    ThreadStore,
)
from rimbook.outline import OutlineStore
from rimbook.planning_entities import EntityNetworkService, PlanningEntityStore
from rimbook.pipeline import Checker, Planner, Writer, PostWritePipeline
from rimbook.project import ProjectPaths, scaffold_project
from rimbook.versioning import VersionManager


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
        self._prompts: Prompts | None = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.config.llm)
        return self._llm

    @property
    def prompts(self) -> Prompts:
        # Workspace-level overrides from <workspace>/prompts.yaml.
        if self._prompts is None:
            self._prompts = load_prompts(workspace_root())
        return self._prompts

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
    def planning_entities(self) -> EntityNetworkService:
        return EntityNetworkService(PlanningEntityStore(self.paths))

    @property
    def window(self) -> SlidingWindow:
        return SlidingWindow(self.paths)

    @property
    def threads(self) -> ThreadStore:
        return ThreadStore(self.paths)

    @property
    def retriever(self):
        """Optional vector retriever, wired in when ``use_vector_retrieval`` is on."""
        if not self.config.generation.use_vector_retrieval:
            return None
        try:
            from rimbook.retrieval import VectorRetriever

            return VectorRetriever(self.paths, self.llm)
        except Exception:
            return None

    @property
    def assembler(self) -> ContextAssembler:
        return ContextAssembler(
            self.paths,
            codex=self.codex,
            outline=self.outline,
            entity_state=self.entity_state,
            window=self.window,
            generation=self.config.generation,
            retriever=self.retriever,
            threads=self.threads,
        )

    @property
    def summarizer(self) -> Summarizer:
        return Summarizer(
            self.llm, self.prompts, self.outline,
            trace=self.trace, project_name=self.project_dir.name,
        )

    @property
    def version_manager(self) -> VersionManager:
        return VersionManager(self.paths.versions_dir, self.project_dir)

    @property
    def trace(self) -> TraceStore:
        # Per-project LLM provenance log → <project>/.llm_logs/<date>.jsonl.
        # Persists the prompt/response/usage for every stage so that problems
        # (e.g. entity-id fragmentation) can be traced back to the source.
        return TraceStore(self.project_dir)

    @property
    def writer(self) -> Writer:
        return Writer(
            self.paths,
            llm=self.llm,
            prompts=self.prompts,
            outline=self.outline,
            assembler=self.assembler,
            summarizer=self.summarizer,
            entity_state=self.entity_state,
            codex=self.codex,
            generation=self.config.generation,
            version_manager=self.version_manager,
            trace=self.trace,
            project_name=self.project_dir.name,
        )

    @property
    def planner(self) -> Planner:
        # NOTE: codex must be passed here, otherwise the planner neither shows
        # the existing entity registry to the LLM nor normalizes drifted ids
        # via resolve_entity_ids — which is exactly how the "测试" project ended
        # up with parallel codex entries (char_lin_yuan vs char_linyuan, etc.).
        return Planner(
            self.llm, self.prompts, self.outline,
            codex=self.codex,
            planning_entities=self.planning_entities,
            threads=self.threads,
            trace=self.trace,
            project_name=self.project_dir.name,
            expansion_hard_max_calls=self.config.world_expansion.max_llm_calls,
            expansion_hard_max_entries=self.config.world_expansion.max_total_entries,
            expansion_hard_max_relationships=self.config.world_expansion.max_total_relationships,
        )

    @property
    def checker(self) -> Checker:
        return Checker(
            self.paths,
            llm=self.llm,
            prompts=self.prompts,
            assembler=self.assembler,
            outline=self.outline,
            trace=self.trace,
            project_name=self.project_dir.name,
        )

    @property
    def enricher(self) -> PostWritePipeline:
        return PostWritePipeline(
            llm=self.llm,
            prompts=self.prompts,
            codex=self.codex,
            entity_state=self.entity_state,
            summarizer=self.summarizer,
            generation=self.config.generation,
            version_manager=self.version_manager,
            trace=self.trace,
            project_name=self.project_dir.name,
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
