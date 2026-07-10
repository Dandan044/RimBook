"""Codex (Story Bible) layer: structured entity archives.

The codex is the source of truth for the world — characters, locations,
factions, worldbuilding rules, items, timeline events. Each entry is a
single Markdown file with YAML frontmatter, so a human can edit any of it
in a normal text editor at any time.

Entity *state* (mutable: location, possessions, knowledge, relationships)
lives separately in :mod:`rimbook.memory.entity_state`. This module only
holds the *static* profile of each entity.
"""

from .models import CodexEntry, ENTITY_TYPE_PLURALS, VALID_TYPES
from .store import CodexStore
from .sync import sync_codex_from_states, strip_state_section, LEGACY_STATE_MARKER
from .resolve import (
    guess_type,
    guess_name,
    slugify,
    resolve_entity_id,
    resolve_entity_ids,
    find_duplicates,
    merge_entries,
)
from .migrate import (
    migrate_state_sections,
    merge_duplicate_entities,
    MigrationReport,
    MergeReport,
)

__all__ = [
    "CodexEntry",
    "CodexStore",
    "ENTITY_TYPE_PLURALS",
    "VALID_TYPES",
    "sync_codex_from_states",
    "strip_state_section",
    "LEGACY_STATE_MARKER",
    "guess_type",
    "guess_name",
    "slugify",
    "resolve_entity_id",
    "resolve_entity_ids",
    "find_duplicates",
    "merge_entries",
    "migrate_state_sections",
    "merge_duplicate_entities",
    "MigrationReport",
    "MergeReport",
]
