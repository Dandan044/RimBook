"""Codex file store.

Each entry lives at ``codex/<type-folder>/<id>.md`` with YAML frontmatter.
We use :mod:`frontmatter` to round-trip metadata + body, and :mod:`pydantic`
for validation. The store is intentionally simple: scan the folder, parse
files, return dicts/lists. No database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import frontmatter
from pydantic import ValidationError

from ..project import ProjectPaths
from .models import CodexEntry, ENTITY_TYPE_PLURALS, VALID_TYPES

__all__ = ["CodexStore"]


class CodexStore:
    """Read & write :class:`CodexEntry` objects from disk."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    # ------------------------------------------------------------------
    # File location helpers
    # ------------------------------------------------------------------
    def file_for(self, entity_type: str, entry_id: str) -> Path:
        folder = ENTITY_TYPE_PLURALS.get(entity_type)
        if folder is None:
            raise ValueError(f"Unknown entity type {entity_type!r}")
        return self.paths.codex_subdir(entity_type) / f"{entry_id}.md"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def write(self, entry: CodexEntry) -> Path:
        """Persist an entry to disk, creating its directory if needed."""
        path = self.file_for(entry.type, entry.id)
        path.parent.mkdir(parents=True, exist_ok=True)

        post = frontmatter.Post(entry.body)
        post.metadata = {
            "id": entry.id,
            "name": entry.name,
            "type": entry.type,
            "aliases": entry.aliases,
            "tags": entry.tags,
            "related": entry.related,
        }
        with path.open("w", encoding="utf-8") as fh:
            fh.write(frontmatter.dumps(post, sort_keys=False))
        return path

    def read(self, entry_id: str) -> CodexEntry:
        """Load a single entry by id (searches all type folders)."""
        path = self._find_file(entry_id)
        if path is None:
            raise FileNotFoundError(f"Codex entry {entry_id!r} not found")
        return self._parse_file(path)

    def read_by_type(self, entity_type: str, entry_id: str) -> CodexEntry:
        path = self.file_for(entity_type, entry_id)
        if not path.exists():
            raise FileNotFoundError(f"Codex entry {entry_id!r} not found at {path}")
        return self._parse_file(path)

    def delete(self, entry_id: str) -> bool:
        path = self._find_file(entry_id)
        if path is None:
            return False
        path.unlink()
        return True

    # ------------------------------------------------------------------
    # Listing / search
    # ------------------------------------------------------------------
    def all(self) -> list[CodexEntry]:
        """Load every entry in the codex."""
        return list(self.iter_all())

    def iter_all(self) -> Iterator[CodexEntry]:
        """Yield every entry lazily."""
        for folder in self.paths.codex_dir.iterdir():
            if not folder.is_dir():
                continue
            for md in sorted(folder.glob("*.md")):
                try:
                    yield self._parse_file(md)
                except (ValidationError, ValueError):
                    # Skip malformed files but keep going — humans may be
                    # mid-edit on a file.
                    continue

    def list_by_type(self, entity_type: str) -> list[CodexEntry]:
        """List all entries of a given type."""
        return [e for e in self.iter_all() if e.type == entity_type]

    def find(self, name_or_alias: str) -> CodexEntry | None:
        """Look up an entry by exact name or alias (case-insensitive)."""
        target = name_or_alias.strip().lower()
        for entry in self.iter_all():
            candidates = [entry.name.lower(), *(a.lower() for a in entry.aliases)]
            if target in candidates:
                return entry
        return None

    def get_many(self, entry_ids: list[str]) -> list[CodexEntry]:
        """Load several entries by id, skipping missing ones."""
        out: list[CodexEntry] = []
        for eid in entry_ids:
            try:
                out.append(self.read(eid))
            except FileNotFoundError:
                continue
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _find_file(self, entry_id: str) -> Path | None:
        for entity_type in VALID_TYPES:
            candidate = self.file_for(entity_type, entry_id)
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _parse_file(path: Path) -> CodexEntry:
        with path.open("r", encoding="utf-8") as fh:
            post = frontmatter.load(fh)
        meta = post.metadata or {}
        return CodexEntry(
            id=str(meta.get("id") or path.stem),
            name=str(meta.get("name") or path.stem),
            type=str(meta.get("type") or _type_from_folder(path)),
            aliases=list(meta.get("aliases") or []),
            tags=list(meta.get("tags") or []),
            related=list(meta.get("related") or []),
            body=post.content.strip(),
        )


def _type_from_folder(path: Path) -> str:
    """Infer entity type from the parent folder name (singular form)."""
    folder = path.parent.name
    for t, plural in ENTITY_TYPE_PLURALS.items():
        if plural == folder:
            return t
    return "worldbuilding"  # safe fallback
