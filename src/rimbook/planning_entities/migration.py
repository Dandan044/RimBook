"""One-time migration from legacy ``planning/entities.yaml`` to file-based codex."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
import yaml

from ..project import ProjectPaths
from .models import (
    EntityRelationship,
    PlanningCodexEntry,
    PlanningEntity,
    PlanningRelationship,
    _map_locks_to_entry,
)

__all__ = ["migrate_legacy_entities_yaml"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entity_to_entry(entity) -> PlanningCodexEntry:
    """Map legacy PlanningEntity to a character PlanningCodexEntry."""
    arc = entity.arc
    details = {
        "kind": entity.kind,
        "story_role": entity.story_role,
        "surface_goal": entity.surface_goal,
        "inner_need": entity.inner_need,
        "fear": entity.fear,
        "values": entity.values,
        "flaw": entity.flaw,
        "capabilities": entity.capabilities,
        "limitations": entity.limitations,
        "voice": entity.voice,
        "action_style": entity.action_style,
        "arc": arc.model_dump(mode="json") if arc else {},
    }
    return PlanningCodexEntry(
        id=entity.id,
        name=entity.name,
        type="character",
        aliases=list(entity.aliases),
        tags=list(entity.tags),
        narrative_role=entity.story_role,
        surface_summary=entity.surface_goal,
        secret_truth=entity.secret,
        volume_roles=dict(entity.volume_roles),
        revealed_ref=entity.codex_ref,
        field_locks=_map_locks_to_entry(list(entity.field_locks)),
        source=entity.source or "migration",
        updated_at=entity.updated_at or _now(),
        details=details,
    )


def _relationship_to_planning(rel) -> PlanningRelationship:
    return PlanningRelationship(
        id=rel.id,
        source_id=rel.source_entity_id,
        target_id=rel.target_entity_id,
        relationship_type=rel.relationship_type,
        tags=list(rel.tags),
        status=rel.status,
        source_goal=rel.source_goal,
        target_goal=rel.target_goal,
        stakes=rel.stakes,
        conflict=rel.conflict,
        secret=rel.secret,
        arc=rel.arc,
        field_locks=list(rel.field_locks),
        source=rel.source or "migration",
        updated_at=rel.updated_at or _now(),
    )


def migrate_legacy_entities_yaml(
    paths: ProjectPaths,
    *,
    write_entry,
    write_relationships,
) -> bool:
    """Migrate ``planning/entities.yaml`` into ``planning/codex/`` if needed.

    Returns True when migration ran. Original YAML is preserved; a checkpoint
    copy is stored under ``.versions/`` before any write.
    """
    legacy = paths.planning_entities_file
    if not legacy.exists():
        return False

    raw = yaml.safe_load(legacy.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return False
    entities_raw = raw.get("entities") or []
    relationships_raw = raw.get("relationships") or []
    if not entities_raw and not relationships_raw:
        return False

    checkpoint_dir = paths.versions_dir / "planning_migration"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(legacy, checkpoint_dir / f"entities_{stamp}.yaml")

    from .models import PlanningEntity

    for item in entities_raw:
        if not isinstance(item, dict):
            continue
        try:
            entity = PlanningEntity.model_validate(item)
        except Exception:
            continue
        write_entry(_entity_to_entry(entity))
    rels = []
    for item in relationships_raw:
        if not isinstance(item, dict):
            continue
        try:
            rels.append(EntityRelationship.model_validate(item))
        except Exception:
            continue
    if rels:
        write_relationships([_relationship_to_planning(r) for r in rels])
    return True
