"""Version management for RimBook projects.

Provides:
* :func:`atomic_write` — crash-safe file writes (temp + rename).
* :class:`VersionManager` — incremental checkpoint creation and rollback.
* :class:`ProjectLock` — per-project mutual-exclusion lock for write operations.
"""

from .atomic import atomic_write
from .lock import ProjectLock
from .manager import VersionManager, CheckpointInfo, BranchInfo

__all__ = ["atomic_write", "VersionManager", "ProjectLock", "CheckpointInfo", "BranchInfo"]