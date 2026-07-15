"""Git-like version manager with branches and checkpoint history.

Data model under ``.versions/``::

    HEAD              # text file: current branch name (e.g. "main")
    branches.json     # {"main": "20260713-172435-write-ch1", "alt": "..."}
    journal.jsonl     # append-only operation log
    <ts>-<label>/
      .manifest       # label, timestamp, branch, parent
      files/...       # the snapshot

Each checkout belongs to a *branch*.  Branches form a DAG through
``parent`` pointers in manifests.  Switching branches auto-saves the
current state as a checkpoint, then restores the target branch's files.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["VersionManager", "CheckpointInfo", "BranchInfo"]


@dataclass
class CheckpointInfo:
    """Summary of one checkpoint."""

    name: str
    label: str
    timestamp: str
    branch: str = ""
    parent: str | None = None
    file_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "timestamp": self.timestamp,
            "branch": self.branch,
            "parent": self.parent,
            "file_count": self.file_count,
        }


@dataclass
class BranchInfo:
    """Summary of one branch."""

    name: str
    head: str  # checkpoint name
    is_current: bool = False
    checkpoint_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "head": self.head,
            "is_current": self.is_current,
            "checkpoint_count": self.checkpoint_count,
        }


class VersionManager:
    """Manages checkpoints and branches under ``.versions/``."""

    def __init__(self, versions_dir: Path, project_dir: Path) -> None:
        self.versions_dir = versions_dir
        self.project_dir = project_dir
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self._head_path = self.versions_dir / "HEAD"
        self._branches_path = self.versions_dir / "branches.json"
        self._journal_path = self.versions_dir / "journal.jsonl"
        self._ensure_bootstrap()

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------
    def _ensure_bootstrap(self) -> None:
        """Create default 'main' branch and HEAD if they don't exist."""
        if not self._branches_path.exists():
            self._write_branches({"main": None})
        if not self._head_path.exists():
            self._head_path.write_text("main", encoding="utf-8")

    def _read_head(self) -> str:
        return self._head_path.read_text(encoding="utf-8").strip() or "main"

    def _write_head(self, branch: str) -> None:
        self._head_path.write_text(branch + "\n", encoding="utf-8")

    def _read_branches(self) -> dict[str, str | None]:
        if not self._branches_path.exists():
            return {"main": None}
        return json.loads(self._branches_path.read_text(encoding="utf-8"))

    def _write_branches(self, data: dict[str, str | None]) -> None:
        self._branches_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _append_journal(self, entry: dict[str, Any]) -> None:
        entry["ts"] = time.strftime("%Y%m%d-%H%M%S")
        with self._journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Branch management
    # ------------------------------------------------------------------
    def get_current_branch(self) -> str:
        return self._read_head()

    def list_branches(self) -> list[BranchInfo]:
        branches = self._read_branches()
        current = self.get_current_branch()
        result: list[BranchInfo] = []
        for name, head in branches.items():
            count = len(self._get_branch_checkpoints(name))
            result.append(
                BranchInfo(
                    name=name,
                    head=head or "",
                    is_current=(name == current),
                    checkpoint_count=count,
                )
            )
        return result

    def create_branch(self, name: str, from_checkpoint: str | None = None) -> str:
        """Create a new branch. If *from_checkpoint* is None, branches from
        the current branch's HEAD."""
        branches = self._read_branches()
        if name in branches:
            raise ValueError(f"Branch '{name}' already exists")
        if from_checkpoint is None:
            branches[name] = branches.get(self.get_current_branch())
        else:
            if not (self.versions_dir / from_checkpoint).exists():
                raise FileNotFoundError(f"Checkpoint '{from_checkpoint}' not found")
            branches[name] = from_checkpoint
        self._write_branches(branches)
        self._append_journal({"op": "create_branch", "branch": name, "from": from_checkpoint})
        logger.info("Created branch '%s'", name)
        return name

    def switch_branch(self, name: str) -> str:
        """Save current state as checkpoint, then restore target branch.

        Returns the checkpoint name created for the current state.
        """
        branches = self._read_branches()
        if name not in branches:
            raise ValueError(f"Branch '{name}' not found")
        if name == self.get_current_branch():
            return ""  # already on this branch

        # Auto-save current state.
        current_branch = self.get_current_branch()
        saved = self.create_checkpoint(
            f"auto-switch-from-{current_branch}",
            self._all_project_files(),
        )

        # Update current branch pointer.
        branches[current_branch] = saved
        self._write_branches(branches)

        # Restore target branch with clean state (delete stale files).
        target_head = branches.get(name)
        if target_head:
            self._clean_restore(target_head)

        self._write_head(name)
        self._append_journal({"op": "switch_branch", "from": current_branch, "to": name, "saved": saved})
        logger.info("Switched to branch '%s' (saved current as %s)", name, saved)
        return saved

    def _clean_restore(self, checkpoint_name: str) -> None:
        """Delete all project files (except .versions/) then restore from
        the full state reconstructed by walking the checkpoint parent chain.

        Unlike ``restore_checkpoint``, this method removes files that exist
        in the project but not in the checkpoint — preventing stale data
        from leaking across branches.
        """
        snap_dir = self.versions_dir / checkpoint_name
        if not snap_dir.exists():
            raise FileNotFoundError(f"Checkpoint '{checkpoint_name}' not found")

        # Reconstruct full file state by walking the parent chain.
        # Newer checkpoints win: iterate oldest → newest, overwriting.
        file_map = self._reconstruct_full_state(checkpoint_name)

        # Delete all project files except .versions/.
        for item in self.project_dir.iterdir():
            if item.name == ".versions":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            elif item.is_file():
                item.unlink()

        # Restore files from the reconstructed set.
        for rel, src_dir in file_map.items():
            src = src_dir / rel
            if src.exists():
                dest = self.project_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dest))

        self._append_journal({"op": "clean_restore", "checkpoint": checkpoint_name, "files": len(file_map)})
        logger.info("Clean restore from %s (%d files)", checkpoint_name, len(file_map))

    def _reconstruct_full_state(self, checkpoint_name: str) -> dict[str, Path]:
        """Walk the parent chain from *checkpoint_name* backwards, collecting
        all files.  Returns ``{rel_path: source_checkpoint_dir}`` where newer
        checkpoints take precedence (their entries overwrite older ones).
        """
        # Build index: checkpoint name → CheckpointInfo.
        index: dict[str, "CheckpointInfo"] = {}
        for entry in self.versions_dir.iterdir():
            if not entry.is_dir():
                continue
            info = self._read_checkpoint_info(entry)
            if info:
                index[info.name] = info

        # Walk parent chain, collect checkpoints oldest → newest.
        chain: list[str] = []
        current = checkpoint_name
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            info = index.get(current)
            if info is None:
                break
            chain.append(current)
            current = info.parent
        chain.reverse()  # oldest first

        # Accumulate files; newer checkpoints overwrite older ones.
        file_map: dict[str, Path] = {}
        for cp_name in chain:
            cp_dir = self.versions_dir / cp_name
            for item in cp_dir.rglob("*"):
                if item.is_file() and item.name != ".manifest":
                    rel = str(item.relative_to(cp_dir))
                    file_map[rel] = cp_dir
        return file_map

    def delete_branch(self, name: str) -> bool:
        if name == self.get_current_branch():
            raise ValueError("Cannot delete the current branch")
        branches = self._read_branches()
        if name not in branches:
            return False
        del branches[name]
        self._write_branches(branches)
        self._append_journal({"op": "delete_branch", "branch": name})
        return True

    # ------------------------------------------------------------------
    # Checkpoint CRUD
    # ------------------------------------------------------------------
    def create_checkpoint(self, label: str, files: list[Path]) -> str:
        """Create a checkpoint, recording branch and parent chain."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        name = f"{ts}-{label}"
        snap_dir = self.versions_dir / name
        i = 1
        while snap_dir.exists():
            snap_dir = self.versions_dir / f"{ts}-{label}-{i}"
            i += 1
        snap_dir.mkdir(parents=True)

        branch = self.get_current_branch()

        # Determine parent: last checkpoint on this branch.
        branches = self._read_branches()
        parent = branches.get(branch)

        copied = 0
        for f in files:
            abs_path = f.resolve() if f.is_absolute() else (self.project_dir / f).resolve()
            if not abs_path.exists():
                continue
            rel = abs_path.relative_to(self.project_dir)
            dest = snap_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(abs_path), str(dest))
            copied += 1

        manifest = snap_dir / ".manifest"
        manifest.write_text(
            f"label: {label}\n"
            f"timestamp: {ts}\n"
            f"branch: {branch}\n"
            f"parent: {parent or ''}\n"
            f"files: {copied}\n",
            encoding="utf-8",
        )

        # Advance branch pointer.
        branches[branch] = name
        self._write_branches(branches)

        self._append_journal({
            "op": "checkpoint", "checkpoint": name, "label": label,
            "branch": branch, "parent": parent, "files": copied,
        })
        logger.info("Checkpoint %s (branch=%s, parent=%s, files=%d)", name, branch, parent, copied)
        return name

    def list_checkpoints(self, branch: str | None = None) -> list[CheckpointInfo]:
        """List checkpoints, optionally filtered by branch. Newest first."""
        if branch is None:
            branch = self.get_current_branch()
        result: list[CheckpointInfo] = []
        for entry in sorted(self.versions_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            info = self._read_checkpoint_info(entry)
            if info and (branch is None or info.branch == branch):
                result.append(info)
        return result

    def list_all_checkpoints(self) -> list[CheckpointInfo]:
        """List every checkpoint regardless of branch."""
        result: list[CheckpointInfo] = []
        for entry in sorted(self.versions_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            info = self._read_checkpoint_info(entry)
            if info:
                result.append(info)
        return result

    def restore_checkpoint(
        self, name: str, files: list[Path] | None = None, *,
        delete_missing: bool = False,
    ) -> dict:
        """Restore files from a checkpoint.

        Returns ``{restored, skipped, deleted}``.

        If *delete_missing* is True, files in the *files* list that don't
        exist in the snapshot are **deleted** from the project — they were
        created after the checkpoint was taken and should be removed to
        fully restore the pre-checkpoint state.  Only meaningful when
        *files* is provided (partial restore).
        """
        snap_dir = self.versions_dir / name
        if not snap_dir.exists() or not snap_dir.is_dir():
            raise FileNotFoundError(f"Checkpoint '{name}' not found")

        restored = 0
        skipped = 0
        deleted = 0

        if files is None:
            for item in snap_dir.rglob("*"):
                if item.is_file() and item.name == ".manifest":
                    continue
                if item.is_dir():
                    continue
                rel = item.relative_to(snap_dir)
                dest = self.project_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(dest))
                restored += 1
        else:
            for f in files:
                abs_path = f.resolve() if f.is_absolute() else (self.project_dir / f).resolve()
                rel = abs_path.relative_to(self.project_dir)
                src = snap_dir / rel
                if src.exists():
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(abs_path))
                    restored += 1
                elif delete_missing and abs_path.exists():
                    abs_path.unlink()
                    deleted += 1
                else:
                    skipped += 1

        self._append_journal({
            "op": "restore", "checkpoint": name,
            "restored": restored, "skipped": skipped, "deleted": deleted,
        })
        logger.info(
            "Restored checkpoint %s (%d restored, %d skipped, %d deleted)",
            name, restored, skipped, deleted,
        )
        return {"restored": restored, "skipped": skipped, "deleted": deleted}

    def delete_checkpoint(self, name: str) -> bool:
        """Delete a checkpoint directory. Refuse if any branch points to it."""
        branches = self._read_branches()
        for bname, head in branches.items():
            if head == name:
                raise ValueError(f"Cannot delete checkpoint '{name}': branch '{bname}' points to it")
        snap_dir = self.versions_dir / name
        if not snap_dir.exists():
            return False
        shutil.rmtree(str(snap_dir))
        self._append_journal({"op": "delete_checkpoint", "checkpoint": name})
        return True

    def prune(self, max_keep: int = 50) -> int:
        """Remove oldest checkpoints beyond *max_keep* (per branch)."""
        deleted = 0
        for branch_info in self.list_branches():
            cps = self._get_branch_checkpoints(branch_info.name)
            if len(cps) <= max_keep:
                continue
            # Delete oldest (not pointed to by any branch).
            to_delete = cps[max_keep:]
            for cp in to_delete:
                try:
                    self.delete_checkpoint(cp)
                    deleted += 1
                except ValueError:
                    pass  # skip branch heads
        return deleted

    def get_branch_history(self, branch: str | None = None) -> list[CheckpointInfo]:
        """Return all checkpoints on *branch* in chronological order (oldest first),
        following the parent chain from the branch head backwards."""
        if branch is None:
            branch = self.get_current_branch()
        branches = self._read_branches()
        head = branches.get(branch)
        if not head:
            return []

        # Build index: checkpoint name -> CheckpointInfo.
        index: dict[str, CheckpointInfo] = {}
        for entry in self.versions_dir.iterdir():
            if not entry.is_dir():
                continue
            info = self._read_checkpoint_info(entry)
            if info:
                index[info.name] = info

        # Walk parent chain from head backwards.
        result: list[CheckpointInfo] = []
        current = head
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            info = index.get(current)
            if info is None:
                break
            result.append(info)
            current = info.parent
        result.reverse()  # oldest first
        return result

    def get_fork_points(self) -> dict[str, list[str]]:
        """Return {checkpoint_name: [branch_names...]} for checkpoints that
        have branches forked from them (i.e., their parent points to them)."""
        branches = self._read_branches()
        # Build map: parent_checkpoint -> [branch_names].
        fork_map: dict[str, list[str]] = {}
        for bname, head in branches.items():
            if not head:
                continue
            snap_dir = self.versions_dir / head
            if not snap_dir.exists():
                continue
            info = self._read_checkpoint_info(snap_dir)
            if info and info.parent:
                fork_map.setdefault(info.parent, []).append(bname)
        return fork_map

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _read_checkpoint_info(self, snap_dir: Path) -> CheckpointInfo | None:
        manifest = snap_dir / ".manifest"
        if not manifest.exists():
            return None
        data: dict[str, str] = {}
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if ": " in line:
                k, v = line.split(": ", 1)
                data[k.strip()] = v.strip()
        return CheckpointInfo(
            name=snap_dir.name,
            label=data.get("label", snap_dir.name),
            timestamp=data.get("timestamp", ""),
            branch=data.get("branch", ""),
            parent=data.get("parent") or None,
            file_count=int(data.get("files", 0)),
        )

    def _get_branch_checkpoints(self, branch: str) -> list[str]:
        """Return checkpoint names belonging to *branch*, newest first."""
        result: list[str] = []
        for entry in sorted(self.versions_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            info = self._read_checkpoint_info(entry)
            if info and info.branch == branch:
                result.append(info.name)
        return result

    def _all_project_files(self) -> list[Path]:
        """Return every file under project_dir (excluding .versions)."""
        result: list[Path] = []
        for item in self.project_dir.iterdir():
            if item.name == ".versions":
                continue
            if item.is_file():
                result.append(item)
            elif item.is_dir():
                for f in item.rglob("*"):
                    if f.is_file():
                        result.append(f)
        return result
