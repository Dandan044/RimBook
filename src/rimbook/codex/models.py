"""Codex data models.

A :class:`CodexEntry` is a single world-building fact: one entity, one
location, one faction, etc. Each one carries metadata (id, name, aliases,
tags) used for retrieval + disambiguation, plus a free-form Markdown body
that a human can elaborate as much as they like.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["CodexEntry", "ENTITY_TYPE_PLURALS"]


# Map entity_type -> folder name. We keep this in sync with project.ENTITY_TYPES.
ENTITY_TYPE_PLURALS = {
    "character": "characters",
    "worldbuilding": "worldbuilding",
    "location": "locations",
    "faction": "factions",
    "item": "items",
    "timeline": "timeline",
}

# The entity types that may appear in the codex.
VALID_TYPES = tuple(ENTITY_TYPE_PLURALS.keys())


class CodexEntry(BaseModel):
    """A single, human-editable entry in the Story Bible.

    The body is deliberately unstructured Markdown so authors can record
    whatever matters: for an entity this is usually appearance, backstory,
    personality, and crucially a *voice profile* (speech-style) which the
    checker uses to detect OOC dialogue.
    """

    id: str = Field(..., description="Slug-like unique id, e.g. 'lin_yuxuan'.")
    name: str = Field(..., description="Display name.")
    type: str = Field(..., description=f"One of {VALID_TYPES}.")
    aliases: list[str] = Field(default_factory=list, description="Other names/ nicknames for disambiguation.")
    tags: list[str] = Field(default_factory=list, description="Free-form tags for explicit loading.")
    related: list[str] = Field(default_factory=list, description="ids of related entries (relationships).")
    body: str = Field(default="", description="Free-form Markdown body.")

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        if self.type not in VALID_TYPES:
            raise ValueError(
                f"Invalid codex type {self.type!r}; expected one of {VALID_TYPES}"
            )
        if not self.id:
            raise ValueError("CodexEntry.id must be a non-empty slug")
