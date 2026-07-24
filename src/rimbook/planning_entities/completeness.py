"""Detect and repair incomplete planning-codex entry payloads from LLMs.

Foundation / volume-cast models often omit ``type`` (and other required
fields) while still choosing a sensible id prefix. Silent defaults such as
``type or "character"`` then permanently mis-file entries. This module
detects incompleteness so the planner can batch-ask the model to label them.
"""

from __future__ import annotations

import json
from typing import Any

from ..codex.models import VALID_TYPES

__all__ = [
    "REQUIRED_TEXT_FIELDS",
    "incomplete_entry_fields",
    "merge_entry_labels",
    "partition_raw_entries",
    "render_incomplete_entries",
]

# Text fields that must be non-empty for a newly created planning entry.
REQUIRED_TEXT_FIELDS = (
    "id",
    "name",
    "type",
    "surface_summary",
    "narrative_role",
    "reveal_strategy",
)


def incomplete_entry_fields(
    item: dict[str, Any],
    *,
    require_existence: bool = False,
) -> list[str]:
    """Return names of required fields that are missing or invalid."""
    if not isinstance(item, dict):
        return ["<not_an_object>"]
    missing: list[str] = []

    entry_id = str(item.get("id") or "").strip()
    if not entry_id:
        missing.append("id")

    name = str(item.get("name") or "").strip()
    if not name:
        missing.append("name")

    entry_type = item.get("type")
    if not (
        isinstance(entry_type, str)
        and entry_type.strip() in VALID_TYPES
    ):
        missing.append("type")

    for field_name in ("surface_summary", "narrative_role", "reveal_strategy"):
        if not str(item.get(field_name) or "").strip():
            missing.append(field_name)

    if require_existence:
        if "exists_at_anchor" not in item:
            missing.append("exists_at_anchor")
        elif item.get("exists_at_anchor") is True:
            if not str(item.get("existence_reason") or "").strip():
                missing.append("existence_reason")
        elif item.get("exists_at_anchor") is False:
            # Future existence must either be timeline-typed or carry formation_event
            # — checked later by apply_foundation_entries; only flag blank formation
            # when type is not already timeline.
            normalized_type = (
                entry_type.strip()
                if isinstance(entry_type, str)
                else ""
            )
            if normalized_type != "timeline" and not item.get("formation_event"):
                missing.append("formation_event")

    return missing


def partition_raw_entries(
    raw_entries: list[Any],
    *,
    require_existence: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split raw LLM entries into (complete, incomplete) dict lists.

    Incomplete items keep a ``_missing_fields`` list for the relabel prompt.
    """
    complete: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        missing = incomplete_entry_fields(
            item, require_existence=require_existence,
        )
        if missing:
            payload = dict(item)
            payload["_missing_fields"] = missing
            incomplete.append(payload)
        else:
            complete.append(item)
    return complete, incomplete


def merge_entry_labels(
    original: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Fill only blank/invalid fields on ``original`` from ``patch``."""
    merged = {
        key: value
        for key, value in original.items()
        if key != "_missing_fields"
    }
    if not isinstance(patch, dict):
        return merged

    for key, value in patch.items():
        if key in {"id", "_missing_fields"}:
            continue
        if key == "type":
            if (
                isinstance(value, str)
                and value.strip() in VALID_TYPES
                and (
                    not isinstance(merged.get("type"), str)
                    or merged.get("type", "").strip() not in VALID_TYPES
                )
            ):
                merged["type"] = value.strip()
            continue
        if key == "exists_at_anchor":
            if "exists_at_anchor" not in merged and isinstance(value, bool):
                merged["exists_at_anchor"] = value
            continue
        if key == "formation_event":
            if not merged.get("formation_event") and value:
                merged["formation_event"] = value
            continue
        if key == "details" and isinstance(value, dict):
            base = dict(merged.get("details") or {})
            for detail_key, detail_value in value.items():
                if detail_key not in base or base[detail_key] in (None, ""):
                    base[detail_key] = detail_value
            merged["details"] = base
            continue
        if isinstance(value, str):
            if not str(merged.get(key) or "").strip() and value.strip():
                merged[key] = value.strip()
            continue
        if key not in merged or merged.get(key) in (None, "", [], {}):
            merged[key] = value
    return merged


def render_incomplete_entries(incomplete: list[dict[str, Any]]) -> str:
    """Compact JSON-ish block for the relabel user prompt."""
    rows: list[dict[str, Any]] = []
    for item in incomplete:
        missing = item.get("_missing_fields") or incomplete_entry_fields(item)
        row = {
            "id": item.get("id"),
            "name": item.get("name"),
            "type": item.get("type"),
            "missing_fields": missing,
            "surface_summary": item.get("surface_summary") or "",
            "secret_truth": item.get("secret_truth") or "",
            "narrative_role": item.get("narrative_role") or "",
            "reveal_strategy": item.get("reveal_strategy") or "",
            "exists_at_anchor": item.get("exists_at_anchor", "<missing>"),
            "existence_reason": item.get("existence_reason") or "",
            "aliases": item.get("aliases") or [],
            "tags": item.get("tags") or [],
        }
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False, indent=2)
