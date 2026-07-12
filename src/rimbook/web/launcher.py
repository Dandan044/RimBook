"""Server lifecycle management — background launch, status, stop, restart.

Provides a set of functions to manage the RimBook web server as a background
process on Windows.  The server writes its PID and port to ``~/.rimbook/`` so
that other processes (including the web frontend itself) can query status and
issue stop/restart commands without needing access to the original console.

Usage::

    from rimbook.web.launcher import start_server, stop_server, get_server_status

    info = start_server()           # background launch + open browser
    status = get_server_status()    # {running: True, pid: 12345, port: 8000, url: ...}
    stop_server()                   # graceful SIGTERM + cleanup
"""

from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_RIMBOOK_DIR = Path.home() / ".rimbook"
_PID_FILE = _RIMBOOK_DIR / "server.pid"
_PORT_FILE = _RIMBOOK_DIR / "server.port"

_DEFAULT_PORT = 8000
_PORT_RANGE_END = 8099
_STARTUP_WAIT_SEC = 1.5
_STOP_WAIT_SEC = 5.0


# ---------------------------------------------------------------------------
# Process helpers (Windows-aware)
# ---------------------------------------------------------------------------
def _ensure_data_dir() -> Path:
    _RIMBOOK_DIR.mkdir(parents=True, exist_ok=True)
    return _RIMBOOK_DIR


def _write_pid(pid: int, port: int) -> None:
    """Persist the running server's PID and port to disk."""
    _ensure_data_dir()
    _PID_FILE.write_text(str(pid), encoding="utf-8")
    _PORT_FILE.write_text(str(port), encoding="utf-8")


def _read_pid() -> tuple[int | None, int | None]:
    """Return ``(pid, port)`` from disk, or ``(None, None)`` if files are missing."""
    if _PID_FILE.exists() and _PORT_FILE.exists():
        try:
            pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
            port = int(_PORT_FILE.read_text(encoding="utf-8").strip())
            return pid, port
        except (ValueError, OSError):
            pass
    return None, None


def _delete_pid_files() -> None:
    """Remove the PID / port files (best-effort)."""
    for p in (_PID_FILE, _PORT_FILE):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def _is_process_running(pid: int) -> bool:
    """Return True if a process with *pid* is alive on this machine.

    On Windows we prefer ``psutil`` when available; otherwise we fall back to
    ``tasklist`` which is adequate but slower.
    """
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    # Windows — try psutil first, then tasklist.
    try:
        import psutil
        return psutil.pid_exists(pid)  # type: ignore[no-any-return]
    except ImportError:
        pass

    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # ``tasklist`` returns the PID in the output when found.
        return str(pid) in result.stdout
    except Exception:
        # If we can't check, be conservative — assume it's gone.
        return False


def _kill_process(pid: int) -> bool:
    """Kill *pid* gracefully (SIGTERM on Windows via ``taskkill``)."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------
def find_free_port(start: int = _DEFAULT_PORT, end: int = _PORT_RANGE_END) -> int:
    """Return the first free TCP port in **[start, end]** (inclusive).

    Raises ``RuntimeError`` if the entire range is exhausted.
    """
    for port in range(start, end + 1):
        if _port_is_free(port):
            return port
    raise RuntimeError(f"No free ports in range {start}-{end}")


def _port_is_free(port: int) -> bool:
    """Return True if nothing is listening on ``127.0.0.1:port``."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        sock.connect(("127.0.0.1", port))
        # Connected — port is in use.
        return False
    except (ConnectionRefusedError, socket.timeout, OSError):
        return True
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_server_status() -> dict[str, Any]:
    """Return the current server status as a dictionary.

    Keys
    ----
    running : bool
        Whether the server process is alive.
    pid : int | None
        The PID of the running server (or ``None``).
    port : int | None
        The port the server is listening on (or ``None``).
    url : str | None
        The URL to open in a browser (or ``None``).
    """
    pid, port = _read_pid()
    if pid is not None and _is_process_running(pid):
        url = f"http://localhost:{port}" if port else None
        return {"running": True, "pid": pid, "port": port, "url": url}

    # PID file exists but the process is dead — clean up stale files.
    _delete_pid_files()
    return {"running": False, "pid": None, "port": None, "url": None}


def start_server(
    workspace: str | None = None,
    port: int | None = None,
    *,
    open_browser: bool = True,
    host: str = "127.0.0.1",
) -> dict[str, Any]:
    """Launch the RimBook web server as a background process.

    Parameters
    ----------
    workspace:
        Override ``RIMBOOK_WORKSPACE`` env var.  Defaults to the current
        working directory.
    port:
        Desired port.  Will auto-select a free port if omitted or if the
        requested port is in use.
    open_browser:
        When ``True`` (the default) the default browser is opened at the
        server's URL after a short warm-up delay.
    host:
        Bind address (default ``127.0.0.1``).

    Returns
    -------
    dict
        ``{"running": True, "pid": <int>, "port": <int>, "url": "<str>"}``
    """
    # If already running, return existing info.
    existing = get_server_status()
    if existing["running"]:
        if open_browser and existing["url"]:
            webbrowser.open(existing["url"])
        return existing

    # Pick a port.
    if port is None:
        port = find_free_port(_DEFAULT_PORT, _PORT_RANGE_END)
    elif not _port_is_free(port):
        port = find_free_port(_DEFAULT_PORT, _PORT_RANGE_END)

    # Environment for the child process.
    env = os.environ.copy()
    env["RIMBOOK_HOST"] = host
    env["RIMBOOK_PORT"] = str(port)
    if workspace:
        env["RIMBOOK_WORKSPACE"] = str(Path(workspace).resolve())

    # Determine the python executable — use the one that is running *us* so we
    # respect virtual environments.
    python_exe = sys.executable

    # Build a launcher command that imports and calls main().
    # We use ``-m rimbook.web`` so the import machinery is identical to what a
    # user would invoke via ``rimbook-web``.
    cmd = [python_exe, "-m", "rimbook.web"]

    # Windows: hide the console window.
    kwargs: dict[str, Any] = {"env": env}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(cmd, **kwargs)

    # Persist PID + port immediately.
    _write_pid(proc.pid, port)

    # Give the server a moment to bind.
    time.sleep(_STARTUP_WAIT_SEC)

    # Verify the process is still alive.
    if proc.poll() is not None:
        _delete_pid_files()
        raise RuntimeError(f"Server process exited immediately with code {proc.returncode}")

    url = f"http://localhost:{port}"
    if open_browser:
        webbrowser.open(url)

    return {"running": True, "pid": proc.pid, "port": port, "url": url}


def stop_server(*, force: bool = False) -> bool:
    """Stop the running RimBook web server (if any).

    Parameters
    ----------
    force:
        When ``True``, fall back to ``taskkill /F`` on Windows (forceful
        termination).  Default is graceful.

    Returns
    -------
    bool
        ``True`` if a server was stopped, ``False`` if none was running.
    """
    pid, port = _read_pid()
    if pid is None or not _is_process_running(pid):
        _delete_pid_files()
        return False

    if not _kill_process(pid):
        if force:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid), "/T"],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

    # Wait for the process to exit.
    deadline = time.time() + _STOP_WAIT_SEC
    while _is_process_running(pid) and time.time() < deadline:
        time.sleep(0.3)

    _delete_pid_files()
    return True


def restart_server(
    workspace: str | None = None,
    port: int | None = None,
    *,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Stop (if running) and then re-start the server.

    Parameters match :func:`start_server`.
    """
    stop_server()
    return start_server(workspace=workspace, port=port, open_browser=open_browser)


# ---------------------------------------------------------------------------
# Cleanup on interpreter exit
# ---------------------------------------------------------------------------
def _cleanup_pid_file():
    """Rare case: the server process is us and we exit cleanly."""
    try:
        pid, _ = _read_pid()
        if pid is not None and pid == os.getpid():
            _delete_pid_files()
    except Exception:
        pass


atexit.register(_cleanup_pid_file)
