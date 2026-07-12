"""Create a Windows desktop shortcut for RimBook.

Run this once after cloning the project::

    python create_shortcut.py

A ``RimBook.lnk`` shortcut will be placed on the desktop.  Double-clicking it
launches the server in the background and opens the browser.

The script attempts to use ``pywin32`` first (most reliable on Windows), then
falls back to a pure-PowerShell approach.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _desktop_dir() -> Path:
    """Return the current user's Desktop folder."""
    # Windows standard: %USERPROFILE%\Desktop.  Fall back to ~/Desktop.
    import os
    desktop = os.environ.get("USERPROFILE", str(Path.home()))
    return Path(desktop) / "Desktop"


def _create_with_pywin32(script_path: Path, icon_path: Path | None = None) -> Path:
    """Create a .lnk using pywin32 ``IShellLink``.  Returns the .lnk path."""
    import pythoncom
    from win32com.client import Dispatch

    shortcut_path = _desktop_dir() / "RimBook.lnk"

    shell = Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(shortcut_path))
    shortcut.TargetPath = str(script_path)
    shortcut.WorkingDirectory = str(script_path.parent)
    shortcut.Description = "RimBook — LLM 长篇小说创作工作台"
    shortcut.WindowStyle = 7  # Minimized

    if icon_path and icon_path.exists():
        shortcut.IconLocation = str(icon_path)

    shortcut.Save()
    return shortcut_path


def _create_with_powershell(script_path: Path, icon_path: Path | None = None) -> Path:
    """Create a .lnk using a pure-PowerShell one-liner (no pywin32 needed)."""
    import subprocess

    shortcut_path = _desktop_dir() / "RimBook.lnk"
    ws = "$wsh = New-Object -ComObject WScript.Shell"
    sc = f"$sc = $wsh.CreateShortcut('{shortcut_path}')"
    opts = (
        f"$sc.TargetPath = '{script_path}'; "
        f"$sc.WorkingDirectory = '{script_path.parent}'; "
        f"$sc.Description = 'RimBook — LLM 长篇小说创作工作台'; "
        f"$sc.WindowStyle = 7"
    )
    if icon_path and icon_path.exists():
        opts += f"; $sc.IconLocation = '{icon_path}'"
    save = "$sc.Save()"

    ps_cmd = f"{ws}; {sc}; {opts}; {save}"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return shortcut_path


def main() -> None:
    project_root = Path(__file__).resolve().parent
    script_path = project_root / "start.bat"

    if not script_path.exists():
        print(f"Error: {script_path} not found — run this script from the RimBook project root.")
        sys.exit(1)

    # Try pywin32 first, fall back to PowerShell.
    try:
        import win32com  # noqa: F401
        shortcut = _create_with_pywin32(script_path)
    except ImportError:
        print("pywin32 not installed — using PowerShell fallback...")
        shortcut = _create_with_powershell(script_path)

    print(f"Desktop shortcut created: {shortcut}")


if __name__ == "__main__":
    main()
