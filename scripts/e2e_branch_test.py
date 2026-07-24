"""E2E test: create project, generate 2 chapters, fork branch, regenerate Ch1.

Usage:  python scripts/e2e_branch_test.py
Requires: backend running at http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import sys
import time
import requests

BASE = "http://127.0.0.1:8000/api"
PID = "e2e-branch-test"
ss = requests.Session()

# Ensure project dir is on path so we can inspect files later.
PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), PID)


def api(method, path, **kw):
    url = f"{BASE}{path}"
    r = ss.request(method, url, **kw)
    r.raise_for_status()
    return r


def plan_synopsis():
    print("\n=== 1. Plan synopsis ===")
    r = api("POST", f"/projects/{PID}/outline/synopsis", json={
        "text": "一个年轻的考古学家在沙漠中发现了一座被遗忘的古城，里面藏着一个足以改变人类文明的秘密。"
    })
    d = r.json()
    print(f"  Synopsis: {len(d.get('text',''))} chars")
    return d


def plan_volume():
    print("\n=== 2. Plan volume (v2 SSE) ===")
    url = f"{BASE}/projects/{PID}/outline/volumes/plan"
    with ss.post(url, json={"title": "沙漠古城"}, stream=True) as r:
        r.raise_for_status()
        current_event = None
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = data_str
                if current_event in ("progress", "step"):
                    msg = data.get("message", data) if isinstance(data, dict) else data
                    print(f"  [{current_event}] {msg}")
                elif current_event == "error":
                    raise RuntimeError(f"volume plan failed: {data}")
                elif current_event == "done":
                    print("  ✅ Volume plan done")
                    break
    vols = api("GET", f"/projects/{PID}/outline/volumes").json()
    if not vols:
        raise RuntimeError("volume plan finished but no volume found")
    print(f"  Volume arc: {len(vols[0].get('arc', ''))} chars")
    return vols[0]


def plan_chapter(num, title):
    print(f"\n=== 3. Plan chapter {num}: '{title}' ===")
    r = api("POST", f"/projects/{PID}/outline/chapters", json={
        "number": num, "title": title, "volume": 1,
    })
    d = r.json()
    entities = d.get("entities", [])
    beats = d.get("beats", [])
    print(f"  Entities: {entities}")
    print(f"  Beats: {len(beats)} beat(s)")
    print(f"  Resolved: {d.get('resolved_ids', [])}")
    print(f"  Warnings: {d.get('id_warnings', [])}")
    return d


def write_chapter_via_sse(num):
    """Generate chapter via SSE endpoint and collect all events."""
    print(f"\n=== 4. Write chapter {num} via SSE ===")
    url = f"{BASE}/projects/{PID}/write/{num}"
    events = []
    with ss.get(url, stream=True) as r:
        r.raise_for_status()
        current_event = None
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = data_str
                events.append((current_event, data))
                if current_event == "progress":
                    msg = data.get("message", data) if isinstance(data, dict) else data
                    print(f"  [{current_event}] {msg}")
                else:
                    preview = str(data)[:120]
                    print(f"  [{current_event}] {preview}")
    # Find the draft event
    draft_data = None
    for evt, data in events:
        if evt == "draft":
            draft_data = data
            break
    if draft_data:
        summary = draft_data.get("summary", "") if isinstance(draft_data, dict) else ""
        print(f"  ✅ Chapter {num} done. Summary: {summary[:100]}...")
    else:
        # Last resort: check the draft endpoint
        r2 = api("GET", f"/projects/{PID}/drafts/{num}")
        dd = r2.json()
        if dd.get("exists"):
            print(f"  ✅ Chapter {num} draft exists ({len(dd['text'])} chars)")
        else:
            print(f"  ❌ Chapter {num} has NO draft!")
    return events


def snapshot_state(label):
    """Print current project state: drafts, codex count, entity states count."""
    print(f"\n=== {label} ===")
    # Drafts
    for num in (1, 2, 3):
        try:
            r = api("GET", f"/projects/{PID}/drafts/{num}")
            d = r.json()
            status = f"✓ ({len(d['text'])} chars)" if d.get("exists") else "✗ (不存在)"
            print(f"  draft/ch{num}.md: {status}")
        except Exception:
            print(f"  draft/ch{num}.md: ❌ error")

    # Codex
    try:
        r = api("GET", f"/projects/{PID}/codex")
        entries = r.json().get("entries", [])
        print(f"  codex: {len(entries)} entries -> {[e['id'] for e in entries]}")
        for e in entries:
            revs = len(e.get("revelations", []))
            print(f"    {e['id']}: {revs} revelations, body={len(e.get('body',''))} chars")
    except Exception as ex:
        print(f"  codex: ❌ {ex}")

    # Entity states
    state_dir = os.path.join(PROJECT_DIR, "state", "entities")
    if os.path.isdir(state_dir):
        states = [f for f in os.listdir(state_dir) if f.endswith(".yaml")]
        print(f"  entity states: {len(states)} files -> {states}")
        if states:
            for sf in states[:5]:
                path = os.path.join(state_dir, sf)
                with open(path) as fh:
                    content = fh.read()
                print(f"    {sf}: {len(content)} chars")
    else:
        print("  entity states: (no directory)")

    # Checkpoints
    checkpoints_dir = os.path.join(PROJECT_DIR, ".versions")
    if os.path.isdir(checkpoints_dir):
        cps = sorted(
            [d for d in os.listdir(checkpoints_dir) if os.path.isdir(os.path.join(checkpoints_dir, d))],
            reverse=True,
        )
        print(f"  checkpoints: {len(cps)} -> {cps[:5]}")
    else:
        print("  checkpoints: (none)")

    # Branches
    try:
        r = api("GET", f"/projects/{PID}/branches")
        d = r.json()
        print(f"  branches: current={d.get('current')}, list={[b['name'] for b in d.get('branches',[])]}")
    except Exception as ex:
        print(f"  branches: ❌ {ex}")

    print()


def fork_and_regen(chapter_num):
    """Fork branch from chapter's pre-write checkpoint, then regenerate."""
    print(f"\n=== 5. Fork branch for chapter {chapter_num} ===")
    r = api("POST", f"/projects/{PID}/chapters/{chapter_num}/fork-for-regen", json={
        "branch_name": f"regen-ch{chapter_num}",
    })
    d = r.json()
    print(f"  Branch: {d.get('branch')}")
    print(f"  From checkpoint: {d.get('from_checkpoint_label')}")
    print(f"  Previous branch: {d.get('previous_branch')}")
    print(f"  Hint: {d.get('hint')}")
    return d


def main():
    # Clean up any previous test project.
    try:
        api("DELETE", f"/projects/{PID}")
        print("Deleted previous test project.")
        time.sleep(0.5)
    except Exception:
        pass

    # Create fresh project.
    r = api("POST", "/projects", json={
        "name": PID, "title": "分支测试", "author": "E2E",
    })
    print(f"Created project: {r.json()['id']}")

    # Enable auto_checkpoint.
    api("PUT", f"/projects/{PID}/config", json={
        "generation": {"auto_checkpoint": True, "auto_enrich": True, "max_checkpoints": 20},
    })
    print("Enabled auto_checkpoint.")

    # Plan synopsis + volume + 2 chapters.
    plan_synopsis()
    plan_volume()
    plan_chapter(1, "沙漠入口")
    plan_chapter(2, "古城深处")

    # Generate chapters.
    write_chapter_via_sse(1)
    write_chapter_via_sse(2)

    # Snapshot state after Ch2.
    snapshot_state("AFTER Ch2 generated")

    # Fork branch for Ch1 re-generation.
    fork_and_regen(1)

    # Snapshot state after fork (should be pre-Ch1 state — no drafts, clean codex).
    snapshot_state("AFTER fork (should be pre-Ch1: no drafts, clean codex)")

    # Now regenerate Ch1 on the new branch.
    write_chapter_via_sse(1)

    # Final snapshot.
    snapshot_state("AFTER regenerating Ch1 on new branch")
    print("=== E2E test complete ===")


if __name__ == "__main__":
    main()
