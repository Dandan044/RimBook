"""Outline layer: synopsis, volumes, and chapter beats.

The outline is the *plan* of the novel and the home of the summary tree.
Chapter beats (what should happen) are authored here; chapter summaries
(what *did* happen) get written back here too, so the file for each chapter
holds both its plan and its realized recap.
"""

from .models import (
    ChapterOutline,
    VolumeOutline,
    SceneBeat,
    ChapterSummary,
)
from .store import OutlineStore

__all__ = [
    "ChapterOutline",
    "VolumeOutline",
    "SceneBeat",
    "ChapterSummary",
    "OutlineStore",
]
