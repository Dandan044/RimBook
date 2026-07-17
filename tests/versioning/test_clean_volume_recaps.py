"""Tests for volume-recap cleanup membership."""

from __future__ import annotations

from pathlib import Path

from rimbook.outline.models import ChapterOutline, VolumeOutline
from rimbook.outline.store import OutlineStore
from rimbook.project import scaffold_project
from rimbook.versioning.cleanup import clean_volume_recaps_post_chapter


def _store(tmp_path: Path) -> OutlineStore:
    return OutlineStore(scaffold_project(tmp_path / "project", exist_ok=True))


def test_clean_recap_uses_chapter_volume_pointers(tmp_path):
    store = _store(tmp_path)
    store.write_volume(
        VolumeOutline(number=1, title="A", arc="arc", chapters=[], ending="end", recap="r1")
    )
    store.write_volume(
        VolumeOutline(number=2, title="B", arc="arc", chapters=[], ending="end", recap="r2")
    )
    store.write_chapter(ChapterOutline(number=5, title="c5", volume=1, beats=[]))
    store.write_chapter(ChapterOutline(number=1, title="c1", volume=2, beats=[]))

    cleared = clean_volume_recaps_post_chapter(store, 5)
    assert cleared == 1
    assert store.read_volume(1).recap == ""
    assert store.read_volume(2).recap == "r2"


def test_clean_recap_skips_empty_membership(tmp_path):
    store = _store(tmp_path)
    store.write_volume(
        VolumeOutline(number=1, title="A", arc="arc", chapters=[], ending="end", recap="keep")
    )
    cleared = clean_volume_recaps_post_chapter(store, 1)
    assert cleared == 0
    assert store.read_volume(1).recap == "keep"
