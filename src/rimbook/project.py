"""Project layout and scaffolding.

A "novel project" is just a directory on disk with a conventional layout.
Everything RimBook needs lives in files humans can read and edit directly,
which keeps the "intervene at any stage" workflow frictionless.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["ProjectPaths", "locate_project", "scaffold_project"]

# Canonical subdirectories of a novel project.
_SUBDIRS = (
    "codex/characters",
    "codex/worldbuilding",
    "codex/locations",
    "codex/factions",
    "codex/items",
    "codex/timeline",
    "outline",
    "outline/chapters",
    "outline/volumes",
    "planning",
    "planning/codex/characters",
    "planning/codex/worldbuilding",
    "planning/codex/locations",
    "planning/codex/factions",
    "planning/codex/items",
    "planning/codex/timeline",
    "drafts",
    "final",
    "state",
    ".versions",
)

# Codex entity types map 1:1 to their folder names.
ENTITY_TYPES = ("character", "worldbuilding", "location", "faction", "item", "timeline")


@dataclass(frozen=True)
class ProjectPaths:
    """Strongly-typed paths to every part of a novel project."""

    root: Path

    # --- top level -------------------------------------------------------
    @property
    def config_file(self) -> Path:
        return self.root / "config.yaml"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def versions_dir(self) -> Path:
        return self.root / ".versions"

    @property
    def vector_dir(self) -> Path:
        return self.state_dir / "vector"

    # --- codex -----------------------------------------------------------
    @property
    def codex_dir(self) -> Path:
        return self.root / "codex"

    def codex_subdir(self, entity_type: str) -> Path:
        # entity_type matches the directory name (singular -> plural folder)
        folder = f"{entity_type}s" if not entity_type.endswith("s") else entity_type
        return self.codex_dir / folder

    # --- outline ---------------------------------------------------------
    @property
    def synopsis_file(self) -> Path:
        return self.root / "outline" / "synopsis.md"

    @property
    def style_file(self) -> Path:
        """Project style bible (voice card) — narrative POV/tone/taboo rules."""
        return self.root / "outline" / "style.md"

    @property
    def story_so_far_file(self) -> Path:
        """Rolling whole-book recap, updated as chapters are written."""
        return self.root / "outline" / "story_so_far.md"

    @property
    def threads_file(self) -> Path:
        """Plot-thread ledger (foreshadowing / suspense / promises)."""
        return self.state_dir / "threads.yaml"

    # --- author-side planning --------------------------------------------
    @property
    def planning_dir(self) -> Path:
        """Private author-planning data, kept separate from reader-facing Codex."""
        return self.root / "planning"

    @property
    def planning_entities_file(self) -> Path:
        """Legacy single-file entity network (migration input only)."""
        return self.planning_dir / "entities.yaml"

    @property
    def planning_codex_dir(self) -> Path:
        """Author-side full planning codex (six types, unrevealed facts allowed)."""
        return self.planning_dir / "codex"

    def planning_codex_subdir(self, entry_type: str) -> Path:
        """Folder for one planning-codex type (mirrors revealed codex layout)."""
        from .codex.models import ENTITY_TYPE_PLURALS

        folder = ENTITY_TYPE_PLURALS.get(entry_type)
        if folder is None:
            raise ValueError(f"Unknown planning codex type {entry_type!r}")
        return self.planning_codex_dir / folder

    @property
    def planning_relationships_file(self) -> Path:
        """Cross-type relationship network for the author-side planning codex."""
        return self.planning_dir / "relationships.yaml"

    @property
    def planning_expansion_state_file(self) -> Path:
        """Checkpoint for the latest resumable world-expansion run."""
        return self.planning_dir / "expansion-state.yaml"

    @property
    def planning_graph_layout_file(self) -> Path:
        """Purely presentational node positions for the relationship graph."""
        return self.planning_dir / "graph-layout.yaml"

    @property
    def reviews_dir(self) -> Path:
        """Macro editorial review reports."""
        return self.state_dir / "reviews"

    @property
    def volumes_dir(self) -> Path:
        return self.root / "outline" / "volumes"

    @property
    def chapters_dir(self) -> Path:
        return self.root / "outline" / "chapters"

    def chapter_outline(self, number: int) -> Path:
        return self.chapters_dir / f"ch{number:03d}.md"

    def volume_outline(self, number: int) -> Path:
        return self.volumes_dir / f"vol{number:02d}.md"

    def volume_beats_file(self, number: int) -> Path:
        """Beat pipeline data for a volume (volNN.beats.yaml)."""
        return self.volumes_dir / f"vol{number:02d}.beats.yaml"

    def volume_framework_file(self, number: int) -> Path:
        """Writing-framework + cast briefing for a volume (volNN.framework.yaml)."""
        return self.volumes_dir / f"vol{number:02d}.framework.yaml"

    # --- prose -----------------------------------------------------------
    @property
    def drafts_dir(self) -> Path:
        return self.root / "drafts"

    def draft_file(self, number: int) -> Path:
        return self.drafts_dir / f"ch{number:03d}.md"

    def context_snapshot_file(self, number: int) -> Path:
        """Write-time assembled context for chapter *number* (JSON)."""
        return self.drafts_dir / f"ch{number:03d}.context.json"

    @property
    def final_dir(self) -> Path:
        return self.root / "final"

    def final_file(self, number: int) -> Path:
        return self.final_dir / f"ch{number:03d}.md"


def locate_project(start: Path | None = None) -> Path:
    """Walk upwards from *start* to find a project (a dir with config.yaml)."""
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "config.yaml").exists():
            return candidate
    raise FileNotFoundError(
        f"No RimBook project found (no config.yaml) at or above {here}"
    )


def scaffold_project(root: Path, *, exist_ok: bool = False) -> ProjectPaths:
    """Create the empty directory tree for a new novel project."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=exist_ok)
    for sub in _SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return ProjectPaths(root=root)
