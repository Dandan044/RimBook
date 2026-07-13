"""Atomic file-write utility.

Writes to a temporary sibling file then atomically replaces the target
via ``os.replace``.  Because ``os.replace`` is atomic on the same
filesystem, a crash (power loss, signal kill) will leave either the old
file intact or the new file in place — never a truncated half-write.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically.

    The temporary file is created in the same directory as *path* (so
    ``os.replace`` stays on the same filesystem).  Parent directories are
    created if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use a named temp file in the SAME directory to guarantee atomic rename.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), suffix=path.suffix + ".tmp", prefix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
        os.replace(tmp_name, str(path))
    except BaseException:
        # Clean up the temp file on any failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Binary variant of :func:`atomic_write`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), suffix=path.suffix + ".tmp", prefix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise