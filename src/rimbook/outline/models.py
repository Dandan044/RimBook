"""Outline data models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "MicroScene", "SceneBeat", "RawBeat", "RefinedBeat", "ChapterAssignment",
    "VolumeBeatData", "ChapterOutline", "VolumeOutline", "ChapterSummary",
]


class MicroScene(BaseModel):
    """A fine-grained beat unit — one performable moment inside a SceneBeat.

    ``intent`` is the primary creative brief. Modality fields (sensory / action /
    dialogue / event) are filled only when relevant — empty means that modality
    does not apply (e.g. an environment-only beat leaves action/dialogue blank).
    """

    intent: str = Field(
        default="",
        description="Creative intent of this moment (atmosphere, reveal, silence, object, etc.).",
    )
    sensory: str = Field(
        default="",
        description="Environment / sensory / atmosphere direction (optional).",
    )
    action: str = Field(default="", description="Character action when people are involved (optional).")
    dialogue: str = Field(default="", description="Dialogue direction (optional).")
    event: str = Field(default="", description="Plot turn in this micro-moment (optional).")
    technique: str = Field(default="", description="Craft technique, e.g. 环境隐喻.")
    pacing: str = Field(default="", description="Pacing: 缓起/加速/留白/爆发/收束/过渡.")
    words: int = Field(default=0, ge=0, description="Target word count for this beatlet.")


class SceneBeat(BaseModel):
    """One scene's worth of plan within a chapter beat."""

    goal: str = Field(..., description="What this scene should accomplish.")
    conflict: str = Field(default="", description="The central tension of the scene.")
    outcome: str = Field(default="", description="Where the scene should land.")
    # ids of codex entities this scene explicitly involves (drives context loading)
    entities: list[str] = Field(default_factory=list)
    scenes: list[MicroScene] = Field(
        default_factory=list,
        description="Fine-grained micro-scenes produced by Step 3b.",
    )


class RawBeat(BaseModel):
    """A volume-level narrative beat — the atomic unit before chapter grouping."""

    id: str = Field(..., description="Stable identifier, e.g. 'b01', 'b02'.")
    goal: str = Field(..., description="What this narrative moment accomplishes.")
    conflict: str = Field(default="", description="The central tension.")
    outcome: str = Field(default="", description="Where this beat lands.")
    entities: list[str] = Field(default_factory=list)
    momentum: str = Field(default="", description="Narrative momentum: what emotional/directional shift this beat creates.")


class RefinedBeat(RawBeat):
    """Legacy Step-3a craft fields (kept for beats.yaml backward compat).

    New pipeline writes MicroScene under ChapterOutline.beats instead.
    """

    technique: str = Field(default="", description="Specific narrative technique.")
    plot_detail: str = Field(default="", description="Expanded plot detail.")
    thematic_expr: str = Field(default="", description="Theme/emotion expressed.")
    pacing_note: str = Field(default="", description="Pacing annotation.")
    is_bridge: bool = Field(default=False, description="Created as a transition beat.")


class ChapterAssignment(BaseModel):
    """The grouping result from Step 3a — which beats form which chapter."""

    chapter: int = Field(..., description="Assigned chapter number.")
    title: str = ""
    beat_ids: list[str] = Field(default_factory=list, description="Ordered beat ids in this chapter.")
    purpose: str = ""
    value_shift: str = ""
    tension: int = Field(default=0, ge=0, le=5)
    hook: str = ""
    story_date: str = ""
    elapsed: str = ""
    keynote: list[str] = Field(
        default_factory=list,
        description="Chapter undertone: implicit constraints that must permeate prose.",
    )


class VolumeBeatData(BaseModel):
    """The full beat pipeline state for one volume, stored as volNN.beats.yaml."""

    volume: int
    step: int = Field(default=2, description="Pipeline progress: 2=raw beats done, 3=grouped+microscened.")
    raw_beats: list[RawBeat] = Field(default_factory=list)
    refined_beats: list[RefinedBeat] = Field(default_factory=list)
    chapter_map: list[ChapterAssignment] = Field(default_factory=list)


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
    # Implicit chapter undertone — must permeate, must not be stated outright.
    keynote: list[str] = Field(default_factory=list)
    # The realized summary, filled in after the chapter is written
    summary: str = ""
    # --- pacing / structure (planner-provided, optional) ---
    purpose: str = Field(default="", description="Narrative function of this chapter.")
    value_shift: str = Field(default="", description="Emotional value shift, e.g. '希望→绝望'.")
    tension: int = Field(default=0, ge=0, le=5, description="Tension level 1-5 (0 = unset).")
    hook: str = Field(default="", description="The end-of-chapter hook to leave the reader with.")
    # --- in-story clock ---
    story_date: str = Field(default="", description="In-story date/time of this chapter.")
    elapsed: str = Field(default="", description="Time elapsed since the previous chapter.")

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
    # Realized recap generated after the volume is written (hierarchical memory).
    recap: str = Field(default="", description="Post-write recap of what actually happened in this volume.")

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        if self.number < 1:
            raise ValueError("volume number must be >= 1")
