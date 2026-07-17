from pathlib import Path

from rimbook.outline.models import ChapterOutline, VolumeOutline
from rimbook.outline.store import OutlineStore
from rimbook.project import scaffold_project


def _store(tmp_path: Path) -> OutlineStore:
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    return OutlineStore(paths)


def test_sync_volume_chapters_from_chapter_pointers(tmp_path):
    store = _store(tmp_path)
    store.write_volume(VolumeOutline(number=1, title="A", arc="arc", chapters=[], ending="end"))
    store.write_chapter(ChapterOutline(number=3, title="c3", volume=1, beats=[]))
    store.write_chapter(ChapterOutline(number=1, title="c1", volume=1, beats=[]))
    store.write_chapter(ChapterOutline(number=2, title="c2", volume=2, beats=[]))

    nums = store.sync_volume_chapters(1)
    assert nums == [1, 3]
    vol = store.read_volume(1)
    assert vol is not None
    assert vol.chapters == [1, 3]
