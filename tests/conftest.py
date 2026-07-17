"""Shared pytest fixtures for RimBook tests."""

from __future__ import annotations

from pathlib import Path

from rimbook.outline.store import OutlineStore
from rimbook.project import scaffold_project


def make_outline_store(tmp_path: Path) -> OutlineStore:
    """Build an OutlineStore backed by a temporary scaffolded project."""
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    return OutlineStore(paths)
