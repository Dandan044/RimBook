"""Server lifecycle management routes — query status, start, stop, restart.

The **stop** and **restart** endpoints run *inside* the server process.  On
Windows, ``taskkill`` cannot reliably kill a process from within itself, so
we use :func:`os._exit` after flushing the HTTP response via
:class:`BackgroundTasks`.

**Restart** spawns a detached supervisor that:
1. waits for this process to exit
2. kills every RimBook instance / frees the app port range
3. rebuilds the Vue frontend into ``static/``
4. starts a fresh server and opens the browser
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from rimbook.web.launcher import (
    _delete_pid_files,
    find_free_port,
    get_server_status,
    spawn_full_restart_supervisor,
)

router = APIRouter(prefix="/api/server", tags=["server"])


class StartRequest(BaseModel):
    workspace: str | None = None
    port: int | None = None
    rebuild: bool = True


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
    """Full restart via a detached supervisor.

    Response returns immediately; the supervisor then kills duplicates,
    rebuilds the frontend (unless ``rebuild=false``), and relaunches.
    """
    status = get_server_status()
    port = req.port or status.get("port") or find_free_port()
    workspace = req.workspace or os.environ.get("RIMBOOK_WORKSPACE")

    supervisor_pid = spawn_full_restart_supervisor(
        workspace=workspace,
        port=int(port) if port else None,
        open_browser=True,
        wait_pid=os.getpid(),
        rebuild=req.rebuild,
    )

    # Clean our own PID files; the supervisor will start a fresh server.
    _delete_pid_files()
    _schedule_exit(tasks, delay=0.5)

    return {
        "running": False,
        "port": port,
        "url": f"http://localhost:{port}",
        "action": "restarting",
        "supervisor_pid": supervisor_pid,
        "message": "正在清理进程、重建前端并重新启动…",
    }
