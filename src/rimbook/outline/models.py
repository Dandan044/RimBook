"""Outline data models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["SceneBeat", "ChapterOutline", "VolumeOutline", "ChapterSummary"]


class SceneBeat(BaseModel):
    """One scene's worth of plan within a chapter beat."""

    goal: str = Field(..., description="What this scene should accomplish.")
    conflict: str = Field(default="", description="The central tension of the scene.")
    outcome: str = Field(default="", description="Where the scene should land.")
    # ids of codex entities this scene explicitly involves (drives context loading)
    entities: list[str] = Field(default_factory=list)


class ChapterOutline(BaseModel):
    """The plan for a single chapter — its 'beat'."""

    number: int
    title: str = ""
    volume: int | None = None
    beats: list[SceneBeat] = Field(default_factory=list)
    # ids of codex entities this chapter explicitly involves
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # Authorial notes: foreshadowing to plant/resolve, constraints, bans
    notes: str = ""
    # The realized summary, filled in after the chapter is written
    summary: str = ""

    def all_entities(self) -> list[str]:
        """Union of chapter-level and per-scene entity ids (deduped, ordered)."""
        seen: set[str] = set()
        out: list[str] = []
        for eid in [*self.entities, *(e for b in self.beats for e in b.entities)]:
            if eid and eid not in seen:
                seen.add(eid)
                out.append(eid)
        return out

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        if self.number < 1:
            raise ValueError("chapter number must be >= 1")


class ChapterSummary(BaseModel):
    """A realized recap of a written chapter (mirrors :class:`ChapterOutline.summary`)."""

    number: int
    summary: str = ""


class VolumeOutline(BaseModel):
    """The plan for one volume/arc of the novel."""

    number: int
    title: str = ""
    arc: str = Field(default="", description="What this volume is about.")
    chapters: list[int] = Field(default_factory=list, description="Chapter numbers in this volume.")
    ending: str = Field(default="", description="How this volume concludes / the hook into the next.")

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        if self.number < 1:
            raise ValueError("volume number must be >= 1")
