"""File-backed persistence for the author-side full planning codex."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import frontmatter
import yaml
from pydantic import ValidationError

from ..codex.models import ENTITY_TYPE_PLURALS, VALID_TYPES
from ..project import ProjectPaths
from ..versioning import atomic_write
from .migration import migrate_legacy_entities_yaml
from .models import (
    EntityNetwork,
    PlanningCodexEntry,
    PlanningEntity,
    PlanningRelationship,
)

__all__ = ["PlanningCodexStore", "PlanningEntityStore"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_entry(entry: PlanningCodexEntry) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "id": entry.id,
        "name": entry.name,
        "type": entry.type,
        "aliases": entry.aliases,
        "tags": entry.tags,
        "relationship_refs": entry.relationship_refs,
        "revealed_ref": entry.revealed_ref,
        "surface_summary": entry.surface_summary,
        "secret_truth": entry.secret_truth,
        "narrative_role": entry.narrative_role,
        "reveal_strategy": entry.reveal_strategy,
        "volume_roles": entry.volume_roles,
        "field_locks": entry.field_locks,
        "source": entry.source,
        "updated_at": entry.updated_at,
    }
    if entry.details:
        meta["details"] = entry.details
    return meta


class PlanningCodexStore:
    """CRUD store for ``planning/codex/<type>/<id>.md`` + ``relationships.yaml``."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self._migration_done = False

    def ensure_migrated(self) -> None:
        if self._migration_done:
            return
        self._migration_done = True
        if self._has_codex_files():
            return
        migrate_legacy_entities_yaml(
            self.paths,
            write_entry=self._write_entry_internal,
            write_relationships=self._write_relationships_internal,
        )

    def file_for(self, entry_type: str, entry_id: str) -> Path:
        folder = ENTITY_TYPE_PLURALS.get(entry_type)
        if folder is None:
            raise ValueError(f"Unknown entry type {entry_type!r}")
        return self.paths.planning_codex_subdir(entry_type) / f"{entry_id}.md"

    # ------------------------------------------------------------------
    # Entries
    # ------------------------------------------------------------------
    def list_entries(self, entry_type: str | None = None) -> list[PlanningCodexEntry]:
        self.ensure_migrated()
        entries = list(self.iter_entries(entry_type))
        return sorted(entries, key=lambda e: (e.type, e.name))

    def iter_entries(self, entry_type: str | None = None) -> Iterator[PlanningCodexEntry]:
        self.ensure_migrated()
        types = [entry_type] if entry_type else list(VALID_TYPES)
        for t in types:
            folder = self.paths.planning_codex_subdir(t)
            if not folder.is_dir():
                continue
            for md in sorted(folder.glob("*.md")):
                try:
                    yield self._parse_file(md)
                except (ValidationError, ValueError):
                    continue

    def get_entry(self, entry_id: str) -> PlanningCodexEntry:
        self.ensure_migrated()
        path = self._find_file(entry_id)
        if path is None:
            raise FileNotFoundError(f"规划设定条目 {entry_id!r} 不存在")
        return self._parse_file(path)

    def get_entry_by_type(self, entry_type: str, entry_id: str) -> PlanningCodexEntry:
        self.ensure_migrated()
        path = self.file_for(entry_type, entry_id)
        if not path.exists():
            raise FileNotFoundError(f"规划设定条目 {entry_id!r} 不存在")
        return self._parse_file(path)

    def save_entry(self, entry: PlanningCodexEntry) -> PlanningCodexEntry:
        self.ensure_migrated()
        entry.updated_at = _now()
        self._write_entry_internal(entry)
        return entry

    def delete_entry(self, entry_id: str) -> bool:
        self.ensure_migrated()
        path = self._find_file(entry_id)
        if path is None:
            return False
        path.unlink()
        rels = self.list_relationships()
        remaining = [
            r for r in rels
            if r.source_id != entry_id and r.target_id != entry_id
        ]
        if len(remaining) != len(rels):
            self._write_relationships_internal(remaining)
        return True

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    def list_relationships(self) -> list[PlanningRelationship]:
        self.ensure_migrated()
        path = self.paths.planning_relationships_file
        if not path.exists():
            return []
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return []
        items = raw.get("relationships") or []
        out: list[PlanningRelationship] = []
        for item in items:
            if isinstance(item, dict):
                try:
                    out.append(PlanningRelationship.model_validate(item))
                except ValidationError:
                    continue
        return out

    def get_relationship(self, relationship_id: str) -> PlanningRelationship:
        for rel in self.list_relationships():
            if rel.id == relationship_id:
                return rel
        raise FileNotFoundError(f"规划关系 {relationship_id!r} 不存在")

    def save_relationship(self, relationship: PlanningRelationship) -> PlanningRelationship:
        self.ensure_migrated()
        known = {e.id for e in self.list_entries()}
        missing = {
            eid for eid in (relationship.source_id, relationship.target_id) if eid not in known
        }
        if missing:
            raise ValueError(f"关系引用了不存在的条目: {', '.join(sorted(missing))}")
        relationship.updated_at = _now()
        rels = self.list_relationships()
        for idx, existing in enumerate(rels):
            if existing.id == relationship.id:
                rels[idx] = relationship
                break
        else:
            rels.append(relationship)
        self._write_relationships_internal(rels)
        return relationship

    def delete_relationship(self, relationship_id: str) -> bool:
        rels = self.list_relationships()
        remaining = [r for r in rels if r.id != relationship_id]
        if len(remaining) == len(rels):
            return False
        self._write_relationships_internal(remaining)
        return True

    def read_network(self) -> EntityNetwork:
        return EntityNetwork(
            entries=self.list_entries(),
            relationships=self.list_relationships(),
            updated_at=_now(),
        )

    def read_graph_layout(self) -> dict[str, Any]:
        path = self.paths.planning_graph_layout_file
        if not path.exists():
            return {"nodes": {}, "viewport": {}}
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"nodes": {}, "viewport": {}}

    def write_graph_layout(self, layout: dict[str, Any]) -> None:
        payload = {
            "version": 1,
            "nodes": dict(layout.get("nodes") or {}),
            "viewport": dict(layout.get("viewport") or {}),
            "updated_at": _now(),
        }
        atomic_write(
            self.paths.planning_graph_layout_file,
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        )

    def set_field_lock(
        self,
        item_type: str,
        item_id: str,
        field_name: str,
        locked: bool,
    ) -> None:
        from .models import _LOCK_TO_ENTRY

        field_name = _LOCK_TO_ENTRY.get(field_name, field_name)
        if item_type == "entry":
            item_type = "entity"
        if item_type == "entity":
            entry = self.get_entry(item_id)
            if field_name not in entry.field_locks and locked:
                entry.field_locks.append(field_name)
            elif field_name in entry.field_locks and not locked:
                entry.field_locks.remove(field_name)
            self.save_entry(entry)
            return
        if item_type == "relationship":
            rel = self.get_relationship(item_id)
            if field_name not in rel.field_locks and locked:
                rel.field_locks.append(field_name)
            elif field_name in rel.field_locks and not locked:
                rel.field_locks.remove(field_name)
            self.save_relationship(rel)
            return
        raise FileNotFoundError(f"未知条目类型 {item_type!r}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _has_codex_files(self) -> bool:
        root = self.paths.planning_codex_dir
        if not root.is_dir():
            return False
        return any(root.rglob("*.md"))

    def _write_entry_internal(self, entry: PlanningCodexEntry) -> None:
        path = self.file_for(entry.type, entry.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Long-form detail belongs in the Markdown body rather than YAML
        # frontmatter. ``body`` is a backward-compatible alias for old files.
        post = frontmatter.Post(entry.detail or entry.body)
        post.metadata = _serialize_entry(entry)
        atomic_write(path, frontmatter.dumps(post, sort_keys=False))

    def _write_relationships_internal(self, relationships: list[PlanningRelationship]) -> None:
        path = self.paths.planning_relationships_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "relationships": [r.model_dump(mode="json") for r in relationships],
            "updated_at": _now(),
        }
        atomic_write(
            path,
            yaml.dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
        )

    def _find_file(self, entry_id: str) -> Path | None:
        for entry_type in VALID_TYPES:
            candidate = self.file_for(entry_type, entry_id)
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _parse_file(path: Path) -> PlanningCodexEntry:
        with path.open("r", encoding="utf-8") as fh:
            post = frontmatter.load(fh)
        meta = post.metadata or {}
        entry_type = str(meta.get("type") or _type_from_folder(path))
        return PlanningCodexEntry(
            id=str(meta.get("id") or path.stem),
            name=str(meta.get("name") or path.stem),
            type=entry_type,
            aliases=list(meta.get("aliases") or []),
            tags=list(meta.get("tags") or []),
            relationship_refs=list(meta.get("relationship_refs") or []),
            revealed_ref=str(meta.get("revealed_ref") or meta.get("codex_ref") or ""),
            surface_summary=str(meta.get("surface_summary") or ""),
            secret_truth=str(meta.get("secret_truth") or ""),
            narrative_role=str(meta.get("narrative_role") or ""),
            reveal_strategy=str(meta.get("reveal_strategy") or ""),
            detail=str(meta.get("detail") or post.content).strip(),
            volume_roles=dict(meta.get("volume_roles") or {}),
            field_locks=list(meta.get("field_locks") or []),
            source=str(meta.get("source") or "manual"),
            updated_at=str(meta.get("updated_at") or ""),
            details=dict(meta.get("details") or {}),
            body=post.content.strip(),
        )


def _type_from_folder(path: Path) -> str:
    folder = path.parent.name
    for t, plural in ENTITY_TYPE_PLURALS.items():
        if plural == folder:
            return t
    return "character"


class PlanningEntityStore(PlanningCodexStore):
    """Backward-compatible wrapper exposing legacy entity/relationship CRUD."""

    def list_entities(self) -> list[PlanningEntity]:
        return [e.to_planning_entity() for e in self.list_entries("character")]

    def get_entity(self, entity_id: str) -> PlanningEntity:
        entry = self.get_entry(entity_id)
        if entry.type != "character":
            raise FileNotFoundError(f"规划实体 {entity_id!r} 不存在")
        return entry.to_planning_entity()

    def save_entity(self, entity: PlanningEntity) -> PlanningEntity:
        entry = PlanningCodexEntry.from_planning_entity(entity)
        self.save_entry(entry)
        return entity

    def delete_entity(self, entity_id: str) -> bool:
        try:
            entry = self.get_entry(entity_id)
        except FileNotFoundError:
            return False
        if entry.type != "character":
            return False
        return self.delete_entry(entity_id)

    def write_network(self, network: EntityNetwork) -> None:
        for entry in network.entries:
            self.save_entry(entry)
        self._write_relationships_internal(network.relationships)

    def save_relationship(self, relationship: PlanningRelationship) -> PlanningRelationship:
        if hasattr(relationship, "source_entity_id"):
            data = relationship.model_dump(mode="json")
            if "source_id" not in data or not data["source_id"]:
                data["source_id"] = relationship.source_entity_id
            if "target_id" not in data or not data["target_id"]:
                data["target_id"] = relationship.target_entity_id
            relationship = PlanningRelationship.model_validate(data)
        return super().save_relationship(relationship)
