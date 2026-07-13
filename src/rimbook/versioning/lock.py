"""Per-project PID-based file lock.

For a single-user desktop app, PID-based locking is simpler and more
robust than fcntl/msvcrt.  Each lock file contains the PID of the holder;
stale locks (dead PIDs) are automatically cleaned up.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

__all__ = ["ProjectLock", "LockTimeoutError"]


class LockTimeoutError(RuntimeError):
    """Raised when a lock cannot be acquired within the timeout."""


def _pid_alive(pid: int) -> bool:
    """Check if a process with *pid* is still running."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


class ProjectLock:
    """PID-based per-project mutual-exclusion lock."""

    def __init__(self, project_dir: Path) -> None:
        lock_dir = project_dir / ".versions"
        lock_dir.mkdir(parents=True, exist_ok=True)
        self._lock_path = lock_dir / ".write.lock"
        self._acquired = False

    def acquire(self, timeout: float = 30.0) -> None:
        """Acquire the lock. Cleans up stale locks automatically."""
        deadline = time.monotonic() + timeout
        my_pid = os.getpid()

        while True:
            try:
                # Read existing lock file.
                if self._lock_path.exists():
                    content = self._lock_path.read_text(encoding="utf-8").strip()
                    try:
                        holder_pid = int(content)
                    except ValueError:
                        holder_pid = 0

                    # If holder is us or dead, we can take over.
                    if holder_pid != my_pid and _pid_alive(holder_pid):
                        raise OSError("Lock held by live process")

                # Write our PID.
                self._lock_path.write_text(str(my_pid), encoding="utf-8")
                self._acquired = True
                return

            except OSError:
                if time.monotonic() > deadline:
                    raise LockTimeoutError(
                        f"Could not acquire project lock within {timeout}s"
                    )
                time.sleep(0.5)

    def release(self) -> None:
        """Release the lock."""
        if not self._acquired:
            return
        try:
            if self._lock_path.exists():
                content = self._lock_path.read_text(encoding="utf-8").strip()
                if content == str(os.getpid()):
                    self._lock_path.unlink()
        except OSError:
            pass
        finally:
            self._acquired = False

    def __enter__(self) -> "ProjectLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()