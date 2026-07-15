#!/usr/bin/env python
"""One-shot repair script for fragmented codex entities.

Entity fragmentation happens when the planner writes drifted ids into the
chapter outline (e.g. ``char_linyuan`` next to the original ``char_lin_yuan``)
and the enricher, before the resolve-based dedup fix, created *new* codex
files for them. Result: two codex bodies + two state files describing one
character.

This script is idempotent: it scans the project with
:func:`rimbook.codex.resolve.find_duplicates`, merges each duplicate group
through :func:`merge_entries`, then rewrites every place ids may appear so
the canonical id wins:

* codex/  — files are merged/deleted by ``merge_entries`` itself.
* state/entities/ — state YAMLs renamed / merged into the canonical id.
* outline/chapters/*.md, outline/volumes/*.md, outline/synopsis.md — the
  ``entities:`` front-matter lists and any inline id references.
* drafts/*.md — inline id mentions are rewritten (best-effort textual).

Run::

    python scripts/fix_fragmented_codex.py <project_dir> [--apply]

Without ``--apply`` it prints a plan and exits (dry-run).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Make the package importable when run from a repo checkout.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from rimbook.codex import CodexStore
from rimbook.codex.resolve import DuplicateGroup, find_duplicates, merge_entries
from rimbook.memory.entity_state import EntityStateStore
from rimbook.project import ProjectPaths

# Entity ids follow type-prefix_underscore_or_alnum slug rules; matching
# them as whole words (delimited by non-slug chars) avoids clobbering
# substrings of other ids.
_ID_BOUNDARY = r"(?![A-Za-z0-9_])"


def _pick_canonical(group: list) -> str:
    """Choose the canonical id for a duplicate group.

    We prefer the *older* form — the one a ch1-style planner would adopt.
    Heuristics, in order:
      1. ids containing an underscore (e.g. ``char_lin_yuan``) — the original
         convention. Among them, prefer the id seen in the lowest-numbered
         chapter's outline (so ch1 wins over ch2 for the same entity).
      2. Fall back to the richest entry (longest body + more aliases), which
         is what :func:`find_duplicates` itself picks.
    """
    underscored = [e for e in group if "_" in e.id.split("_", 1)[-1]]
    if underscored:
        return min(underscored, key=lambda e: e.id).id
    return max(group, key=lambda e: (len(e.body), len(e.aliases))).id


def _scan_groups(codex: CodexStore) -> list[DuplicateGroup]:
    """Detect duplicate groups via two heuristics.

    1. :func:`find_duplicates` (core-slug overlap): catches
       ``char_lin_yuan`` ↔ ``char_linyuan``.
    2. Same ``name`` fallback: catches semantic duplicates where the core
       slugs differ — e.g. ``set_grey_human``  (name=灰人) and
       ``set_hui_ren`` (name=灰人), or ``set_purple_grass`` /
       ``set_zijing_cao``. We only group entries whose name is non-empty
       and identical (case-insensitive), and never merge two entries whose
       ids look genuinely different *and* have distinct explicit names.

    ``find_duplicates`` picks the *richest* entry as canonical, but the rich
    one is often the later (ch2) file; we re-pick canonical via
    :func:`_pick_canonical` to keep the oldest (ch1) naming convention.
    """
    by_id_seen: set[str] = set()
    groups: list[DuplicateGroup] = []

    # --- step 1: core-slug overlap ---
    raw_groups = find_duplicates(codex)
    for g in raw_groups:
        all_ids = [g.canonical_id, *g.aliases_ids]
        entries = []
        for eid in all_ids:
            try:
                entries.append(codex.read(eid))
            except FileNotFoundError:
                pass
        if not entries:
            continue
        canonical_id = _pick_canonical(entries)
        others = [e.id for e in entries if e.id != canonical_id]
        groups.append(
            DuplicateGroup(
                canonical_id=canonical_id,
                aliases_ids=others,
                reason=g.reason,
            )
        )
        by_id_seen.update(all_ids)

    # --- step 2: same-name fallback ---
    name_to_entries: dict[str, list] = {}
    for e in codex.iter_all():
        if e.id in by_id_seen:
            continue
        key = (e.name or "").strip().lower()
        # Skip generic placeholder names derived from the id slug; those are
        # not real-world names and merging by them is unsafe.
        if not key or key == e.id.lower() or key.startswith("_"):
            continue
        name_to_entries.setdefault(key, []).append(e)

    for name, entries in name_to_entries.items():
        if len(entries) < 2:
            continue
        canonical_id = _pick_canonical(entries)
        others = [e.id for e in entries if e.id != canonical_id]
        groups.append(
            DuplicateGroup(
                canonical_id=canonical_id,
                aliases_ids=others,
                reason=f"shared display name: {name}",
            )
        )
        by_id_seen.update(e.id for e in entries)

    return groups


def _merge_states(
    entity_state: EntityStateStore,
    *,
    canonical_id: str,
    removed_ids: list[str],
) -> None:
    """Combine state files from *removed_ids* into *canonical_id*.

    Strategy (explicit, additive): load canonical + every removed; union the
    knowledge/possessions lists (dedup by content), overwrite location/status
    with the most recently-seen (heuristic: the one with the higher
    ``last_seen_chapter``), and merge relationships. Save under canonical id;
    delete the redundant state files.
    """
    canonical = entity_state.get(canonical_id)
    sources = [entity_state.get(rid) for rid in removed_ids]

    # Pick the highest last_seen_chapter to drive latest-wins fields.
    newest = max([canonical, *sources], key=lambda s: s.last_seen_chapter)
    canonical.location = newest.location or canonical.location
    canonical.status = newest.status or canonical.status
    canonical.last_seen_chapter = max(
        s.last_seen_chapter for s in [canonical, *sources]
    )

    seen_kn: set[str] = set()
    for s in [canonical, *sources]:
        for item in s.knowledge:
            key = (item.fact or "").strip()
            if key and key not in seen_kn:
                seen_kn.add(key)
                if not any((k.fact or "").strip() == key for k in canonical.knowledge):
                    canonical.knowledge.append(item)

    seen_po: set[str] = set()
    for s in [canonical, *sources]:
        for item in s.possessions:
            key = (item.item or "").strip()
            if key and key not in seen_po:
                seen_po.add(key)
                if not any((p.item or "").strip() == key for p in canonical.possessions):
                    canonical.possessions.append(item)

    for s in sources:
        for target_id, standing in s.relationships.items():
            canonical.relationships.setdefault(target_id, standing)

    entity_state.save(canonical)
    for rid in removed_ids:
        path = entity_state._path(rid)
        if path.exists():
            path.unlink()


def _replace_id_in_text(text: str, remap: dict[str, str]) -> tuple[str, int]:
    """Rewrite every occurrence of a removed id → canonical id.

    Matches id tokens delimited by non-slug chars to avoid substring hits.
    Also rewrites YAML list items (`  - char_linyuan`).
    """
    n = 0
    new = text
    for old, canonical in remap.items():
        if old == canonical:
            continue
        pattern = re.compile(
            r"(?<![A-Za-z0-9_])" + re.escape(old) + _ID_BOUNDARY
        )
        new, hits = pattern.subn(canonical, new)
        n += hits
    return new, n


def _rewrite_outline_and_drafts(
    project_dir: Path, remap: dict[str, str]
) -> dict[str, int]:
    """Rewrite outline chapters/volumes/synopsis, drafts, and state files
    to use canonical ids. State YAMLs are treated as plain text here too —
    entity ids can appear as ``location``, ``relationships`` targets, and
    inside provenance strings.

    Returns counts of replaced ids per file (for reporting).
    """
    paths = ProjectPaths(root=project_dir)
    counts: dict[str, int] = {}

    candidates: list[Path] = [paths.synopsis_file]
    if paths.volumes_dir.exists():
        candidates.extend(sorted(paths.volumes_dir.glob("*.md")))
    if paths.chapters_dir.exists():
        candidates.extend(sorted(paths.chapters_dir.glob("*.md")))
    if paths.drafts_dir.exists():
        candidates.extend(sorted(paths.drafts_dir.glob("*.md")))
    # State files may reference drifted ids as location/relationship targets.
    state_dir = paths.state_dir / "entities"
    if state_dir.exists():
        candidates.extend(sorted(state_dir.glob("*.yaml")))

    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new, n = _replace_id_in_text(text, remap)
        if n and new != text:
            path.write_text(new, encoding="utf-8")
            counts[str(path.relative_to(project_dir))] = n
    return counts


def _plan_report(groups: list[DuplicateGroup]) -> None:
    if not groups:
        print("✓ 未发现分裂实体")
        return
    print(f"发现 {len(groups)} 组分裂实体：")
    for g in groups:
        print(f"  • canonical = {g.canonical_id}  ← 合并自 {g.aliases_ids}")
        print(f"      原因：{g.reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path, help="要修复的 RimBook 项目目录")
    parser.add_argument(
        "--apply", action="store_true",
        help="实际写入改动；省略则只打印计划（dry-run）",
    )
    args = parser.parse_args(argv)

    project_dir: Path = args.project_dir.resolve()
    if not (project_dir / "config.yaml").exists():
        print(f"错误：{project_dir} 不是 RimBook 项目", file=sys.stderr)
        return 2

    paths = ProjectPaths(root=project_dir)
    codex = CodexStore(paths)
    entity_state = EntityStateStore(paths)

    groups = _scan_groups(codex)
    _plan_report(groups)
    if not groups:
        return 0
    if not args.apply:
        print("\n（dry-run，未修改任何文件。加 --apply 执行清理）")
        return 0

    print("\n应用合并…")
    for g in groups:
        canonical_id = g.canonical_id
        removed_ids = list(g.aliases_ids)

        # 1. Merge codex entries; remove the duplicate files.
        result = merge_entries(
            codex, into_id=canonical_id, from_ids=removed_ids
        )
        print(
            f"  • codex: {canonical_id} 合入了 {result.removed_ids} "
            f"（remap={result.remap}）"
        )

        # 2. Merge / rename entity state files.
        _merge_states(
            entity_state,
            canonical_id=canonical_id,
            removed_ids=removed_ids,
        )
        print(f"  • state: {canonical_id} 状态已合并并删除冗余文件")

        # 3. Rewrite outline + drafts to use canonical ids.
        counts = _rewrite_outline_and_drafts(project_dir, result.remap)
        if counts:
            print("  • 文件引用重写：")
            for f, n in counts.items():
                print(f"      {f}: {n} 处")

    # 4. Verify: scan again.
    print("\n验收：重新扫描…")
    remaining = _scan_groups(codex)
    if remaining:
        print("⚠ 仍有未消除的分裂：")
        for g in remaining:
            print(f"  • {g.canonical_id} ← {g.aliases_ids}")
        return 1
    print("✓ 所有分裂实体已合并；项目可继续生成后续章节。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())