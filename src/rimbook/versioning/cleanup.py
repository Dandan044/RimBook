"""Content-level cleanup for chapter regen / branch fork.

File-level restore from pre-write checkpoints is the primary mechanism.
These helpers are a safety net for older checkpoints that may not have
snapshotted narrative assets, and for cumulative ledgers that need
chapter-granular stripping.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory.threads import ThreadStore
    from ..outline.store import OutlineStore

logger = logging.getLogger("rimbook.versioning.cleanup")

__all__ = [
    "clean_threads_post_chapter",
    "clean_story_so_far_post_chapter",
    "clean_volume_recaps_post_chapter",
    "clean_reviews_not_in_snapshot",
]


def clean_threads_post_chapter(threads: ThreadStore, number: int) -> int:
    """Remove thread rows / updates contributed by chapters >= *number*.

    Returns the number of threads removed or modified.
    """
    items = threads.all()
    if not items:
        return 0
    kept = []
    changed = 0
    for t in items:
        if t.planted_chapter >= number:
            changed += 1
            continue
        new_updates = [u for u in t.updates if u.chapter < number]
        modified = len(new_updates) != len(t.updates)
        if t.resolved_chapter is not None and t.resolved_chapter >= number:
            t.resolved_chapter = None
            t.status = "progressed" if new_updates else "open"
            modified = True
        if modified:
            t.updates = new_updates
            if t.status == "resolved" and t.resolved_chapter is None:
                t.status = "progressed" if new_updates else "open"
            changed += 1
        kept.append(t)
    if changed:
        threads.save_all(kept)
        logger.info("Cleaned threads ledger for chapters >= %d (%d changes)", number, changed)
    return changed


def clean_story_so_far_post_chapter(outline: OutlineStore, number: int) -> bool:
    """Drop story-so-far when it covers chapters >= *number*.

    Surgical truncation would need another LLM pass; deleting is correct
    because post-write will regenerate it on the next eligible chapter.

    Note: call this *after* file-level restore. A correctly restored
    pre-write story-so-far should have ``upto < number`` and is kept.
    """
    path = outline.paths.story_so_far_file
    if not path.exists():
        return False
    _text, upto = outline.read_story_so_far()
    # upto is the last chapter covered; regenerating *number* requires
    # coverage strictly before that chapter.
    if upto < number:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    logger.info("Removed story_so_far.md (covered up to ch%d, rolling back to ch%d)", upto, number)
    return True


def clean_volume_recaps_post_chapter(outline: OutlineStore, number: int) -> int:
    """Clear realized volume recaps that may include chapters >= *number*."""
    cleared = 0
    for vol in outline.list_volumes():
        if not (vol.recap or "").strip():
            continue
        chs = list(vol.chapters or [])
        # Recap is unsafe if the volume contains any chapter >= N, or if
        # membership is unknown (empty chapters list) while rolling back.
        unsafe = (not chs) or any(c >= number for c in chs)
        if not unsafe:
            continue
        vol.recap = ""
        outline.write_volume(vol)
        cleared += 1
    if cleared:
        logger.info("Cleared %d volume recap(s) for chapters >= %d", cleared, number)
    return cleared


def clean_reviews_not_in_snapshot(
    reviews_dir: Path, snapshot_rels: set[str] | None = None, *,
    delete_all: bool = False,
) -> int:
    """Delete macro-review reports that are absent from the pre-write snapshot.

    If *delete_all* is True, remove every review (used when the checkpoint
    predates review tracking and we cannot prove which reports are safe).
    """
    if not reviews_dir.exists():
        return 0
    deleted = 0
    for f in sorted(reviews_dir.glob("*.md")):
        rel = f"state/reviews/{f.name}"
        if delete_all or (snapshot_rels is not None and rel not in snapshot_rels):
            try:
                f.unlink()
                deleted += 1
            except OSError:
                pass
    if deleted:
        logger.info("Deleted %d review report(s) not in pre-write snapshot", deleted)
    return deleted
