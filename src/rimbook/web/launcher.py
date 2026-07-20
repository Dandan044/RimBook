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


def _find_all_rimbook_pids() -> list[int]:
    """Find every OS process currently running the RimBook web server.

    Scans running processes by command line (looking for the ``rimbook.web``
    module invocation) instead of trusting only the tracked PID file. This
    catches orphaned/stray instances left behind by a previous crash, a
    forced shutdown, or repeated launches on different days/ports — exactly
    the scenario that once caused a two-day-old process to keep silently
    serving stale code while every restart via the tracked PID file appeared
    to succeed.
    """
    pids: list[int] = []

    try:
        import psutil

        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (p.info.get("name") or "").lower()
                if "python" not in name:
                    continue
                cmdline = " ".join(p.info.get("cmdline") or [])
            except Exception:
                continue
            if "rimbook.web" in cmdline or "rimbook-web" in cmdline:
                pids.append(p.info["pid"])
        return pids
    except ImportError:
        pass

    if sys.platform == "win32":
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                    "| ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }",
                ],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
            for line in result.stdout.splitlines():
                pid_str, sep, cmdline = line.partition("|")
                if not sep:
                    continue
                if "rimbook.web" in cmdline or "rimbook-web" in cmdline:
                    try:
                        pids.append(int(pid_str.strip()))
                    except ValueError:
                        pass
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "rimbook.web"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass

    return pids


def _force_kill_pid(pid: int) -> None:
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


def _cmdline_looks_like_rimbook(cmdline: str) -> bool:
    """True only for RimBook web server invocations (not arbitrary Python apps)."""
    cl = cmdline.lower()
    return (
        "rimbook.web" in cl
        or "rimbook-web" in cl
        or "rimbook.web.full_restart" in cl
    )


def _is_rimbook_server_pid(pid: int) -> bool:
    """Confirm *pid* is a RimBook web server before we kill it."""
    if pid <= 0:
        return False
    try:
        import psutil

        p = psutil.Process(pid)
        name = (p.name() or "").lower()
        if "python" not in name and "uvicorn" not in name:
            return False
        cmdline = " ".join(p.cmdline() or [])
        return _cmdline_looks_like_rimbook(cmdline)
    except ImportError:
        pass
    except Exception:
        return False

    # Fallback without psutil: only trust PIDs already discovered by cmdline scan.
    return pid in set(_find_all_rimbook_pids())


def kill_all_rimbook_processes(*, exclude_pid: int | None = None) -> int:
    """Kill every RimBook web-server process found on this machine.

    Unlike :func:`stop_server` (which only stops the PID recorded in
    ``server.pid``), this scans the full process list so stray instances from
    previous days/crashes are cleaned up too.

    Safety: only processes whose command line contains ``rimbook.web`` /
    ``rimbook-web`` are targeted. Other Python apps on ports 8000–8099 are
    **not** killed.

    Returns the number of processes killed. Safe to call when nothing is
    running (returns ``0``).
    """
    my_pid = os.getpid()
    pids = {
        pid for pid in _find_all_rimbook_pids()
        if pid != my_pid and pid != exclude_pid and _is_rimbook_server_pid(pid)
    }

    if not pids:
        _delete_pid_files()
        return 0

    for pid in pids:
        _kill_process(pid)

    deadline = time.time() + _STOP_WAIT_SEC
    while any(_is_process_running(pid) for pid in pids) and time.time() < deadline:
        time.sleep(0.3)

    # Anything still alive after the graceful wait gets force-killed.
    for pid in pids:
        if _is_process_running(pid):
            _force_kill_pid(pid)

    _delete_pid_files()
    return len(pids)


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
    force_restart: bool = False,
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
    force_restart:
        When ``True``, unconditionally kill *every* RimBook server process
        found on this machine (see :func:`kill_all_rimbook_processes`) before
        launching a fresh one — even ones not tracked by the PID file (e.g.
        orphaned from a previous crash or a launch on a different day). This
        guarantees the shortcut always runs the current code instead of
        silently reusing a stale, long-running process. Default ``False``
        preserves the old "reuse if already running" behavior for callers
        (like the in-app restart button) that manage the process lifecycle
        themselves.

    Returns
    -------
    dict
        ``{"running": True, "pid": <int>, "port": <int>, "url": "<str>"}``
    """
    if force_restart:
        kill_all_rimbook_processes()
    else:
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
    rebuild: bool = True,
) -> dict[str, Any]:
    """Full restart: kill all instances, rebuild frontend, start fresh.

    Prefer this over a bare stop/start when the caller is *outside* the
    running server process. In-app Restart uses
    :func:`spawn_full_restart_supervisor` instead (the server cannot rebuild
    itself after it has already exited).
    """
    return run_full_restart_job(
        workspace=workspace,
        port=port,
        open_browser=open_browser,
        wait_pid=None,
        rebuild=rebuild,
    )


# ---------------------------------------------------------------------------
# Full restart (kill-all + frontend rebuild + relaunch)
# ---------------------------------------------------------------------------
_RESTART_LOG = _RIMBOOK_DIR / "full_restart.log"


def find_repo_root() -> Path | None:
    """Locate the RimBook repo root (directory containing ``web/frontend``)."""
    candidates: list[Path] = []
    env = os.environ.get("RIMBOOK_WORKSPACE")
    if env:
        candidates.append(Path(env).resolve())
    candidates.extend(Path(__file__).resolve().parents)
    candidates.append(Path.cwd().resolve())
    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if (c / "web" / "frontend" / "package.json").is_file():
            return c
    return None


def _append_restart_log(msg: str) -> None:
    try:
        _ensure_data_dir()
        with _RESTART_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def rebuild_frontend(repo_root: Path | None = None, *, timeout: int = 300) -> Path:
    """Run ``npm run build`` so ``static/`` picks up the latest Vue sources.

    Returns the static output directory. Raises ``RuntimeError`` on failure.
    """
    root = repo_root or find_repo_root()
    if root is None:
        raise RuntimeError("找不到前端工程目录（web/frontend/package.json）")
    frontend = root / "web" / "frontend"
    static_dir = root / "src" / "rimbook" / "web" / "backend" / "static"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    _append_restart_log(f"rebuild_frontend cwd={frontend}")
    kwargs: dict[str, Any] = {
        "cwd": str(frontend),
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run([npm, "run", "build"], **kwargs)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-2000:]
        _append_restart_log(f"rebuild FAILED: {tail}")
        raise RuntimeError(f"前端构建失败（exit {result.returncode}）：{tail}")
    if not static_dir.exists() or not any(static_dir.iterdir()):
        raise RuntimeError(f"前端构建完成但未找到产物目录：{static_dir}")
    _append_restart_log(f"rebuild OK → {static_dir}")
    return static_dir


def run_full_restart_job(
    *,
    workspace: str | None = None,
    port: int | None = None,
    open_browser: bool = True,
    wait_pid: int | None = None,
    rebuild: bool = True,
) -> dict[str, Any]:
    """Synchronous full restart used by the detached supervisor (and CLI)."""
    _append_restart_log(
        f"full_restart begin wait_pid={wait_pid} port={port} rebuild={rebuild}"
    )

    if wait_pid is not None:
        deadline = time.time() + _STOP_WAIT_SEC + 2.0
        while _is_process_running(wait_pid) and time.time() < deadline:
            time.sleep(0.2)
        if _is_process_running(wait_pid):
            _force_kill_pid(wait_pid)
            time.sleep(0.3)

    killed = kill_all_rimbook_processes(exclude_pid=os.getpid())
    _append_restart_log(f"killed {killed} process(es)")

    # Give sockets a moment to release after force-kill.
    time.sleep(0.5)

    if rebuild:
        rebuild_frontend()

    info = start_server(
        workspace=workspace,
        port=port,
        open_browser=open_browser,
        force_restart=True,
    )
    _append_restart_log(f"full_restart done url={info.get('url')} pid={info.get('pid')}")
    return info


def spawn_full_restart_supervisor(
    *,
    workspace: str | None = None,
    port: int | None = None,
    open_browser: bool = True,
    wait_pid: int | None = None,
    rebuild: bool = True,
) -> int:
    """Spawn a detached supervisor that performs :func:`run_full_restart_job`.

    Returns the supervisor PID. The caller (usually the dying server) should
    exit shortly after so the supervisor can take over.
    """
    python_exe = sys.executable
    cmd = [
        python_exe,
        "-m",
        "rimbook.web.full_restart",
    ]
    if workspace:
        cmd.extend(["--workspace", str(Path(workspace).resolve())])
    if port is not None:
        cmd.extend(["--port", str(port)])
    if wait_pid is not None:
        cmd.extend(["--wait-pid", str(wait_pid)])
    if not open_browser:
        cmd.append("--no-browser")
    if not rebuild:
        cmd.append("--skip-build")

    _ensure_data_dir()
    log_fh = _RESTART_LOG.open("a", encoding="utf-8")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_fh,
        "stderr": log_fh,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    _append_restart_log(f"spawn supervisor: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        log_fh.close()
    except OSError:
        pass
    return proc.pid


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
