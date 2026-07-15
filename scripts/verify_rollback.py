"""Verify chapter-1 regen rollback deletes polluted codex/state files."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rimbook.versioning import VersionManager


def main() -> None:
    project = Path("测试").resolve()
    vm = VersionManager(project / ".versions", project)

    cps = vm.list_checkpoints()
    print("Checkpoints (newest first):")
    for c in cps:
        print(f"  {c.name}  label={c.label}")

    matching = [c for c in cps if c.label.startswith("write-ch1-")]
    earliest = matching[-1] if matching else None
    newest = matching[0] if matching else None
    print(f"earliest = {earliest.name if earliest else None}")
    print(f"newest   = {newest.name if newest else None}")

    codex = list((project / "codex").rglob("*.md")) if (project / "codex").exists() else []
    state = list((project / "state").rglob("*.yaml")) if (project / "state").exists() else []
    print(f"BEFORE: codex={len(codex)} state={len(state)}")

    if not earliest:
        print("No write-ch1- checkpoint; abort")
        return

    files = codex + state
    result = vm.restore_checkpoint(earliest.name, files=files, delete_missing=True)
    print("RESTORE result:", result)

    codex2 = list((project / "codex").rglob("*.md")) if (project / "codex").exists() else []
    state2 = list((project / "state").rglob("*.yaml")) if (project / "state").exists() else []
    print(f"AFTER:  codex={len(codex2)} state={len(state2)}")
    if codex2:
        print("Remaining codex:", [str(p.relative_to(project)) for p in codex2])
    if state2:
        print("Remaining state:", [str(p.relative_to(project)) for p in state2])

    ok = result.get("deleted", 0) > 0 and len(codex2) == 0
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
