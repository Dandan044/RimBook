"""Server lifecycle management routes — query status, start, stop, restart.

The **stop** and **restart** endpoints run *inside* the server process.  On
Windows, ``taskkill`` cannot reliably kill a process from within itself, so
we use :func:`os._exit` after flushing the HTTP response via
:class:`BackgroundTasks`.

The **restart** endpoint spawns a replacement child process *before* exiting,
so the user never sees a dead server.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from rimbook.web.launcher import (
    _delete_pid_files,
    _ensure_data_dir,
    _RIMBOOK_DIR,
    _write_pid,
    find_free_port,
    get_server_status,
)

router = APIRouter(prefix="/api/server", tags=["server"])


class StartRequest(BaseModel):
    workspace: str | None = None
    port: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _schedule_exit(tasks: BackgroundTasks, delay: float = 0.4) -> None:
    """Schedule ``os._exit(0)`` after *delay* seconds via background tasks.

    The delay gives the HTTP response time to flush before the process dies.
    """
    def _exit():
        time.sleep(delay)
        os._exit(0)

    tasks.add_task(_exit)


def _spawn_replacement(port: int) -> None:
    """Spawn a *new* server process that will take over the same port.

    The new process inherits ``RIMBOOK_PORT`` and writes its own PID file,
    so the frontend will see it as a continuation of the previous server.
    A bind retry is configured so the new process waits for the old one to
    release the port.
    """
    env = os.environ.copy()
    env["RIMBOOK_PORT"] = str(port)
    env["RIMBOOK_BIND_RETRY"] = "3"  # retry up to 3 times (1s apart)

    python_exe = sys.executable
    cmd = [python_exe, "-m", "rimbook.web"]

    kwargs: dict[str, Any] = {"env": env}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    subprocess.Popen(cmd, **kwargs)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/status")
def status() -> dict[str, Any]:
    """Get the current server process status."""
    return get_server_status()


@router.post("/start")
def start(req: StartRequest) -> dict[str, Any]:
    """Launch the RimBook server as a background process.

    If called from within a running server this is effectively a no-op that
    returns the current status.  Use ``restart`` if you need to replace the
    current process.
    """
    from rimbook.web.launcher import start_server

    existing = get_server_status()
    if existing["running"]:
        return {**existing, "action": "already_running"}

    try:
        info = start_server(
            workspace=req.workspace,
            port=req.port,
            open_browser=True,
        )
        return {**info, "action": "started"}
    except RuntimeError as exc:
        return {"running": False, "error": str(exc), "action": "failed"}


@router.post("/stop")
def stop(tasks: BackgroundTasks) -> dict[str, Any]:
    """Stop the current server process.

    Cleans up PID files and schedules ``os._exit(0)`` via a background task
    so the response is flushed before the process dies.  The frontend will
    see the server as "stopped" immediately.
    """
    # Clean PID files before we die.
    _delete_pid_files()

    # Schedule exit — this guarantees the process actually terminates,
    # unlike ``taskkill`` which may silently fail on self-termination.
    _schedule_exit(tasks)

    return {"running": False, "action": "stopped"}


@router.post("/restart")
def restart(req: StartRequest, tasks: BackgroundTasks) -> dict[str, Any]:
    """Replace the current server with a fresh one on the same port.

    1. Spawns a new server process (child) on the same port.
    2. Cleans up *our* PID files (the child will write its own).
    3. Exits via ``os._exit`` so the child takes over seamlessly.
    """
    status = get_server_status()
    port = status.get("port") or find_free_port()

    if req.port is not None:
        port = req.port

    # Spawn the replacement *before* we die.
    _spawn_replacement(port)

    # Clean our own PID files; the child will write fresh ones.
    _delete_pid_files()

    _schedule_exit(tasks)

    return {
        "running": True,
        "port": port,
        "url": f"http://localhost:{port}",
        "action": "restarted",
    }
