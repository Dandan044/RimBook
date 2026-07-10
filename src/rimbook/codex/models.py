"""Codex data models.

A :class:`CodexEntry` is a single world-building fact: one entity, one
location, one faction, etc. Each one carries metadata (id, name, aliases,
tags) used for retrieval + disambiguation, plus a free-form Markdown body
that a human can elaborate as much as they like.

Structured enrichment (v2):
  * :class:`Revelation` — per-chapter discoveries auto-extracted by the
    enrichment pipeline.  Formerly appended as ``### 🤖 第N章自动揭示``
    markdown inside ``body``; now stored as structured frontmatter.
  * :class:`Contradiction` — flagged inconsistencies between a chapter and
    existing codex.  Can be marked ``resolved`` by the user.
  * :class:`Relationship` — a typed, directional link between two entities,
    replacing the flat ``related: [id, …]`` list.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CodexEntry",
    "Revelation",
    "Contradiction",
    "Relationship",
    "ENTITY_TYPE_PLURALS",
    "VALID_TYPES",
]


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


# ---------------------------------------------------------------------------
# Structured enrichment models (v2)
# ---------------------------------------------------------------------------

class Revelation(BaseModel):
    """A single fact about an entity discovered in a specific chapter."""

    chapter: int = Field(..., ge=1, description="Chapter number where this was revealed.")
    content: str = Field(..., description="The discovered information (1-3 sentences).")
    source: str = Field(
        default="",
        description="Optional quote from the chapter that supports this revelation.",
    )


class Contradiction(BaseModel):
    """A flagged inconsistency between a chapter and existing codex."""

    chapter: int = Field(..., ge=1, description="Chapter where the contradiction was found.")
    description: str = Field(..., description="What contradicts what.")
    evidence: str = Field(default="", description="Quote or reference from the chapter.")
    resolved: bool = Field(default=False, description="True once the user has fixed this.")


class Relationship(BaseModel):
    """A typed, directional link from this entity to another."""

    target: str = Field(..., description="Entity id of the related entity.")
    type: str = Field(
        default="related",
        description="Relationship kind: ally, enemy, lover, family, member_of, located_in, …",
    )
    since_chapter: int = Field(default=1, ge=1, description="Chapter where this relationship began.")
    notes: str = Field(default="", description="Free-text context.")


# ---------------------------------------------------------------------------
# CodexEntry
# ---------------------------------------------------------------------------

class CodexEntry(BaseModel):
    """A single, human-editable entry in the Story Bible.

    The ``body`` is deliberately unstructured Markdown so authors can record
    whatever matters: for an entity this is usually appearance, backstory,
    personality, and crucially a *voice profile* (speech-style) which the
    checker uses to detect OOC dialogue.

    Structured enrichment (v2) lives in the frontmatter fields
    ``revelations``, ``contradictions``, and ``relationships``, keeping the
    body clean and the machine-generated data queryable.
    """

    id: str = Field(..., description="Slug-like unique id, e.g. 'char_chen'.")
    name: str = Field(..., description="Display name.")
    type: str = Field(..., description=f"One of {VALID_TYPES}.")
    aliases: list[str] = Field(default_factory=list, description="Other names / nicknames.")
    tags: list[str] = Field(default_factory=list, description="Free-form tags for explicit loading.")

    # ---- v2 structured fields ----
    revelations: list[Revelation] = Field(
        default_factory=list,
        description="Per-chapter facts discovered by the enrichment pipeline.",
    )
    contradictions: list[Contradiction] = Field(
        default_factory=list,
        description="Flagged inconsistencies between chapter and codex.",
    )
    relationships: list[Relationship] = Field(
        default_factory=list,
        description="Typed, directional links to other entities.",
    )

    # ---- legacy / derived ----
    related: list[str] = Field(
        default_factory=list,
        description="Flat list of related entity ids (derived from relationships).",
    )
    body: str = Field(default="", description="Free-form Markdown body (static profile).")

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        if self.type not in VALID_TYPES:
            raise ValueError(
                f"Invalid codex type {self.type!r}; expected one of {VALID_TYPES}"
            )
        if not self.id:
            raise ValueError("CodexEntry.id must be a non-empty slug")
        # Keep `related` in sync with `relationships`.
        if not self.related and self.relationships:
            self.related = list({r.target for r in self.relationships})
