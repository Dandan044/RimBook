"""Outline file store.

Layout:
* ``outline/synopsis.md`` — pure Markdown, the whole-novel synopsis.
* ``outline/volumes/vol<N>.md`` — YAML frontmatter + Markdown body.
* ``outline/chapters/ch<N>.md`` — YAML frontmatter (beats serialized as a
  list of dicts) + Markdown body (free-form plan notes), plus a
  ``summary`` field filled after writing.

We serialize ``SceneBeat`` lists as lists of dicts inside frontmatter so the
file stays human-editable in any text editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
import yaml

from ..project import ProjectPaths
from ..versioning import atomic_write
from .models import ChapterOutline, SceneBeat, VolumeOutline

__all__ = ["OutlineStore"]


class OutlineStore:
    """Read & write synopsis, volumes, and chapter outlines."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    # ==================================================================
    # Synopsis
    # ==================================================================
    def read_synopsis(self) -> str:
        path = self.paths.synopsis_file
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def write_synopsis(self, text: str) -> Path:
        path = self.paths.synopsis_file
        atomic_write(path, text.strip() + "\n")
        return path

    # ==================================================================
    # Style bible (voice card)
    # ==================================================================
    def read_style(self) -> str:
        path = self.paths.style_file
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def write_style(self, text: str) -> Path:
        path = self.paths.style_file
        atomic_write(path, text.strip() + "\n")
        return path

    # ==================================================================
    # Story-so-far (rolling whole-book recap)
    # ==================================================================
    def read_story_so_far(self) -> tuple[str, int]:
        """Return ``(text, upto_chapter)`` of the rolling story-so-far recap."""
        path = self.paths.story_so_far_file
        if not path.exists():
            return "", 0
        with path.open("r", encoding="utf-8") as fh:
            post = frontmatter.load(fh)
        upto = int((post.metadata or {}).get("upto_chapter") or 0)
        return post.content.strip(), upto

    def write_story_so_far(self, text: str, upto_chapter: int) -> Path:
        path = self.paths.story_so_far_file
        post = frontmatter.Post(text.strip())
        post.metadata = {"upto_chapter": upto_chapter}
        atomic_write(path, frontmatter.dumps(post, sort_keys=False))
        return path

    # ==================================================================
    # Volumes
    # ==================================================================
    def write_volume(self, vol: VolumeOutline) -> Path:
        path = self.paths.volume_outline(vol.number)
        post = frontmatter.Post(vol.arc or "")
        post.metadata = {
            "number": vol.number,
            "title": vol.title,
            "chapters": vol.chapters,
            "ending": vol.ending,
            "recap": vol.recap,
        }
        atomic_write(path, frontmatter.dumps(post, sort_keys=False))
        return path

    def read_volume(self, number: int) -> VolumeOutline | None:
        path = self.paths.volume_outline(number)
        if not path.exists():
            return None
        return self._parse_volume(path)

    def list_volumes(self) -> list[VolumeOutline]:
        out: list[VolumeOutline] = []
        for path in sorted(self.paths.volumes_dir.glob("vol*.md")):
            try:
                vol = self._parse_volume(path)
            except Exception:
                continue
            if vol is not None:
                out.append(vol)
        return out

    def sync_volume_chapters(self, volume_number: int) -> list[int]:
        """Recompute VolumeOutline.chapters from ChapterOutline.volume pointers."""
        vol = self.read_volume(volume_number)
        if vol is None:
            raise FileNotFoundError(f"Volume {volume_number} not found")
        nums = sorted(
            c.number for c in self.list_chapters() if c.volume == volume_number
        )
        if list(vol.chapters or []) != nums:
            vol.chapters = nums
            self.write_volume(vol)
        return nums

    # ==================================================================
    # Chapters
    # ==================================================================
    def write_chapter(self, ch: ChapterOutline) -> Path:
        path = self.paths.chapter_outline(ch.number)

        post = frontmatter.Post(ch.notes or "")
        post.metadata = {
            "number": ch.number,
            "title": ch.title,
            "volume": ch.volume,
            "entities": ch.entities,
            "tags": ch.tags,
            "beats": [b.model_dump() for b in ch.beats],
            "summary": ch.summary,
            "purpose": ch.purpose,
            "value_shift": ch.value_shift,
            "tension": ch.tension,
            "hook": ch.hook,
            "story_date": ch.story_date,
            "elapsed": ch.elapsed,
        }
        atomic_write(path, frontmatter.dumps(post, sort_keys=False))
        return path

    def read_chapter(self, number: int) -> ChapterOutline | None:
        path = self.paths.chapter_outline(number)
        if not path.exists():
            return None
        return self._parse_chapter(path)

    def list_chapters(self) -> list[ChapterOutline]:
        out: list[ChapterOutline] = []
        for path in sorted(self.paths.chapters_dir.glob("ch*.md")):
            try:
                ch = self._parse_chapter(path)
            except Exception:
                continue
            if ch is not None:
                out.append(ch)
        return out

    def last_chapter_number(self) -> int:
        """Highest chapter number that has an outline, or 0 if none."""
        nums = [c.number for c in self.list_chapters()]
        return max(nums) if nums else 0

    def update_chapter_summary(self, number: int, summary: str) -> Path:
        """Write back a realized summary without disturbing the rest of the beat."""
        ch = self.read_chapter(number)
        if ch is None:
            raise FileNotFoundError(f"Chapter outline {number} not found")
        ch.summary = summary
        return self.write_chapter(ch)

    # ==================================================================
    # Parsing internals
    # ==================================================================
    def _parse_volume(self, path: Path) -> VolumeOutline | None:
        with path.open("r", encoding="utf-8") as fh:
            post = frontmatter.load(fh)
        meta = post.metadata or {}
        return VolumeOutline(
            number=int(meta.get("number") or _num_from_name(path, "vol")),
            title=str(meta.get("title", "")),
            arc=post.content.strip(),
            chapters=list(meta.get("chapters") or []),
            ending=str(meta.get("ending", "")),
            recap=str(meta.get("recap", "") or ""),
        )

    def _parse_chapter(self, path: Path) -> ChapterOutline | None:
        with path.open("r", encoding="utf-8") as fh:
            post = frontmatter.load(fh)
        meta = post.metadata or {}
        beats_raw = meta.get("beats") or []
        beats = [SceneBeat(**_clean_beat(b)) for b in beats_raw]
        return ChapterOutline(
            number=int(meta.get("number") or _num_from_name(path, "ch")),
            title=str(meta.get("title", "")),
            volume=meta.get("volume"),
            entities=list(meta.get("entities") or []),
            tags=list(meta.get("tags") or []),
            beats=beats,
            notes=post.content.strip(),
            summary=str(meta.get("summary", "")),
            purpose=str(meta.get("purpose", "") or ""),
            value_shift=str(meta.get("value_shift", "") or ""),
            tension=_safe_tension(meta.get("tension")),
            hook=str(meta.get("hook", "") or ""),
            story_date=str(meta.get("story_date", "") or ""),
            elapsed=str(meta.get("elapsed", "") or ""),
        )


def _num_from_name(path: Path, prefix: str) -> int:
    stem = path.stem
    if stem.startswith(prefix):
        try:
            return int(stem[len(prefix):])
        except ValueError:
            pass
    return 1


def _clean_beat(b: Any) -> dict[str, Any]:
    """Normalize a beat dict coming from YAML (tolerate extra keys)."""
    if not isinstance(b, dict):
        return {"goal": str(b)}
    allowed = {"goal", "conflict", "outcome", "entities"}
    return {k: v for k, v in b.items() if k in allowed}


def _safe_tension(v: Any) -> int:
    """Coerce the tension field to an int in [0, 5]."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return min(max(n, 0), 5)
