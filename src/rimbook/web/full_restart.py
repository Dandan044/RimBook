"""Detached full-restart supervisor.

Invoked as ``python -m rimbook.web.full_restart`` from the in-app Restart
button. Runs *outside* the dying server process so it can:

1. Wait for the old server PID to exit
2. Kill every RimBook server process / free the app port range
3. Rebuild the Vue frontend into ``static/``
4. Start a fresh server and open the browser
"""

from __future__ import annotations

import argparse
import sys
import traceback

from rimbook.web.launcher import run_full_restart_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RimBook full restart supervisor")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--wait-pid", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args(argv)

    try:
        info = run_full_restart_job(
            workspace=args.workspace,
            port=args.port,
            open_browser=not args.no_browser,
            wait_pid=args.wait_pid,
            rebuild=not args.skip_build,
        )
        print(f"OK {info.get('url')} pid={info.get('pid')}", flush=True)
        return 0
    except Exception as exc:
        traceback.print_exc()
        print(f"FAIL {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
