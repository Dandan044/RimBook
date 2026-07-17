"""Tests for chapter/volume deletion and write-time chapter sync."""

from __future__ import annotations

from pathlib import Path

from rimbook.outline.models import ChapterOutline, SceneBeat, VolumeOutline
from rimbook.outline.store import OutlineStore
from rimbook.project import scaffold_project


def _store(tmp_path: Path) -> OutlineStore:
    return OutlineStore(scaffold_project(tmp_path / "project", exist_ok=True))


def test_write_chapter_syncs_volume_chapters(tmp_path):
    store = _store(tmp_path)
    store.write_volume(VolumeOutline(number=1, title="A", arc="a", ending="e"))
    store.write_chapter(
        ChapterOutline(
            number=2,
            title="c2",
            volume=1,
            beats=[SceneBeat(goal="g")],
        )
    )
    vol = store.read_volume(1)
    assert vol is not None
    assert vol.chapters == [2]


def test_delete_chapter_removes_outline_and_syncs(tmp_path):
    store = _store(tmp_path)
    store.write_volume(VolumeOutline(number=1, title="A", arc="a", ending="e"))
    store.write_chapter(ChapterOutline(number=1, title="c1", volume=1, beats=[]))
    store.write_chapter(ChapterOutline(number=2, title="c2", volume=1, beats=[]))
    assert store.delete_chapter(1) is True
    assert store.read_chapter(1) is None
    assert store.read_volume(1).chapters == [2]


def test_delete_volume_cascades_chapters(tmp_path):
    store = _store(tmp_path)
    store.write_volume(VolumeOutline(number=1, title="A", arc="a", ending="e"))
    store.write_chapter(ChapterOutline(number=1, title="c1", volume=1, beats=[]))
    store.paths.draft_file(1).write_text("draft", encoding="utf-8")
    deleted = store.delete_volume(1, cascade_chapters=True)
    assert deleted == [1]
    assert store.read_volume(1) is None
    assert store.read_chapter(1) is None
    assert not store.paths.draft_file(1).exists()
