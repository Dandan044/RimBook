"""LLM trace log browser — read ``.llm_logs/*.jsonl`` for the UI."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import ProjectDeps, get_project_deps

router = APIRouter(prefix="/api/projects/{project_id}", tags=["llm-logs"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PREVIEW_LEN = 200


def _logs_root(deps: ProjectDeps) -> Path:
    root = deps.trace.root
    if root is None:
        raise HTTPException(400, "项目未启用 LLM 日志")
    return root


def _validate_date(date: str) -> str:
    if not _DATE_RE.match(date):
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    return date


def _log_file(deps: ProjectDeps, date: str) -> Path:
    _validate_date(date)
    path = _logs_root(deps) / f"{date}.jsonl"
    # Resolve and ensure we stay inside the logs directory.
    root = _logs_root(deps).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(400, "非法路径") from exc
    return resolved


def _truncate(text: str | None, limit: int = _PREVIEW_LEN) -> str:
    if not text:
        return ""
    s = str(text)
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def _prompt_preview(prompt: Any) -> str:
    if not isinstance(prompt, list):
        return _truncate(str(prompt) if prompt is not None else "")
    parts: list[str] = []
    for m in prompt:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "")
            parts.append(f"[{role}] {_truncate(str(content), 80)}")
        else:
            parts.append(_truncate(str(m), 80))
    return _truncate(" · ".join(parts), _PREVIEW_LEN)


def _usage_total(usage: Any) -> int | None:
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    if isinstance(total, int):
        return total
    pt = usage.get("prompt_tokens") or 0
    ct = usage.get("completion_tokens") or 0
    try:
        return int(pt) + int(ct)
    except (TypeError, ValueError):
        return None


def _summarize(rec: dict[str, Any], index: int) -> dict[str, Any]:
    response = rec.get("response")
    if isinstance(response, (dict, list)):
        response_str = json.dumps(response, ensure_ascii=False, default=str)
    elif response is None:
        response_str = ""
    else:
        response_str = str(response)

    stage = str(rec.get("stage") or "unknown")
    body = extract_response_body(stage, response_str)["body"]

    return {
        "index": index,
        "ts": rec.get("ts") or "",
        "stage": stage,
        "chapter": rec.get("chapter"),
        "model": rec.get("model") or "",
        "usage_total": _usage_total(rec.get("usage")),
        "has_error": bool(rec.get("error")),
        "error": _truncate(str(rec["error"]), 120) if rec.get("error") else None,
        "prompt_preview": _prompt_preview(rec.get("prompt")),
        "response_preview": _truncate(body or response_str),
        "prompt_chars": sum(
            len(str(m.get("content", ""))) if isinstance(m, dict) else len(str(m))
            for m in (rec.get("prompt") or [])
        ) if isinstance(rec.get("prompt"), list) else 0,
        "response_chars": len(response_str),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(500, f"读取日志失败: {exc}") from exc
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _try_parse_json(text: str) -> Any | None:
    s = (text or "").strip()
    if not s:
        return None
    # Strip markdown fences if present.
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Best-effort: first {...} or [...] span.
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = s.find(open_c)
            end = s.rfind(close_c)
            if start >= 0 and end > start:
                try:
                    return json.loads(s[start : end + 1])
                except json.JSONDecodeError:
                    continue
    return None


def _fmt_list(items: Any, *, bullet: str = "•") -> list[str]:
    lines: list[str] = []
    if not isinstance(items, list):
        return lines
    for it in items:
        if isinstance(it, str) and it.strip():
            lines.append(f"{bullet} {it.strip()}")
        elif isinstance(it, dict):
            # Prefer common readable keys.
            for key in ("description", "name", "title", "note", "content", "summary"):
                val = it.get(key)
                if isinstance(val, str) and val.strip():
                    extra = it.get("id") or it.get("entity_id") or it.get("type") or ""
                    prefix = f"[{extra}] " if extra else ""
                    lines.append(f"{bullet} {prefix}{val.strip()}")
                    break
            else:
                lines.append(f"{bullet} {json.dumps(it, ensure_ascii=False, default=str)}")
    return lines


def _body_from_checker(data: dict[str, Any]) -> str:
    lines: list[str] = []
    overall = str(data.get("overall") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if overall:
        lines.append(f"【总评】{overall}")
    if summary:
        lines.append(summary)
    issues = data.get("issues") or []
    if isinstance(issues, list) and issues:
        lines.append("")
        lines.append(f"问题（{len(issues)}）：")
        for i, iss in enumerate(issues, 1):
            if not isinstance(iss, dict):
                continue
            sev = str(iss.get("severity") or "").strip()
            cat = str(iss.get("category") or "").strip()
            desc = str(iss.get("description") or "").strip()
            evidence = str(iss.get("evidence") or "").strip()
            suggestion = str(iss.get("suggestion") or "").strip()
            head = f"{i}. [{sev}/{cat}] {desc}".strip()
            lines.append(head)
            if evidence:
                lines.append(f"   原文：{evidence}")
            if suggestion:
                lines.append(f"   建议：{suggestion}")
    elif overall == "通过" or (isinstance(issues, list) and not issues):
        if not lines:
            lines.append("通过，未发现问题。")
    return "\n".join(lines).strip()


def _body_from_planner(data: dict[str, Any]) -> str:
    lines: list[str] = []
    title = str(data.get("title") or "").strip()
    if title:
        lines.append(f"标题：{title}")
    for key, label in (
        ("purpose", "本章目的"),
        ("value_shift", "价值转变"),
        ("hook", "章末钩子"),
        ("notes", "备注"),
        ("story_date", "故事日期"),
        ("elapsed", "时间跨度"),
    ):
        val = str(data.get(key) or "").strip()
        if val:
            lines.append(f"{label}：{val}")
    tension = data.get("tension")
    if tension is not None and str(tension).strip() != "":
        lines.append(f"张力：{tension}")
    entities = data.get("entities") or []
    if isinstance(entities, list) and entities:
        lines.append("实体：" + "、".join(str(x) for x in entities if str(x).strip()))
    tags = data.get("tags") or []
    if isinstance(tags, list) and tags:
        lines.append("标签：" + "、".join(str(x) for x in tags if str(x).strip()))
    beats = data.get("beats") or []
    if isinstance(beats, list) and beats:
        lines.append("")
        lines.append("场景 Beat：")
        for i, b in enumerate(beats, 1):
            if not isinstance(b, dict):
                continue
            lines.append(f"{i}. 目标：{str(b.get('goal') or '').strip()}")
            conflict = str(b.get("conflict") or "").strip()
            outcome = str(b.get("outcome") or "").strip()
            if conflict:
                lines.append(f"   冲突：{conflict}")
            if outcome:
                lines.append(f"   结果：{outcome}")
            ents = b.get("entities") or []
            if isinstance(ents, list) and ents:
                lines.append("   实体：" + "、".join(str(x) for x in ents))
    return "\n".join(lines).strip()


def _body_from_enricher(data: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = str(data.get("summary") or "").strip()
    if summary:
        lines.append(summary)
        lines.append("")
    new_entities = data.get("new_entities") or []
    if isinstance(new_entities, list) and new_entities:
        lines.append(f"新实体（{len(new_entities)}）：")
        for ent in new_entities:
            if not isinstance(ent, dict):
                continue
            name = str(ent.get("name") or ent.get("id") or "").strip()
            etype = str(ent.get("type") or "").strip()
            body = str(ent.get("body") or ent.get("summary") or "").strip()
            head = f"• {name}" + (f"（{etype}）" if etype else "")
            lines.append(head)
            if body:
                lines.append(f"  {_truncate(body, 240)}")
            revs = ent.get("revelations") or []
            if isinstance(revs, list) and revs:
                for r in revs[:3]:
                    if isinstance(r, dict):
                        c = str(r.get("content") or "").strip()
                        if c:
                            lines.append(f"  揭示：{_truncate(c, 160)}")
                    elif isinstance(r, str) and r.strip():
                        lines.append(f"  揭示：{_truncate(r, 160)}")
    enrich = data.get("enrichments") or data.get("updates") or []
    if isinstance(enrich, list) and enrich:
        lines.append("")
        lines.append(f"档案充实（{len(enrich)}）：")
        lines.extend(_fmt_list(enrich))
    contradictions = data.get("contradictions") or []
    if isinstance(contradictions, list) and contradictions:
        lines.append("")
        lines.append(f"矛盾（{len(contradictions)}）：")
        lines.extend(_fmt_list(contradictions))
    return "\n".join(lines).strip()


def _body_from_threads(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, label in (
        ("new_threads", "新线索"),
        ("progressed", "推进"),
        ("resolved", "回收"),
    ):
        items = data.get(key) or []
        if isinstance(items, list) and items:
            lines.append(f"{label}（{len(items)}）：")
            lines.extend(_fmt_list(items))
            lines.append("")
    return "\n".join(lines).strip()


def _body_from_entity_delta(data: dict[str, Any]) -> str:
    lines: list[str] = []
    entities = data.get("entities") or []
    if not isinstance(entities, list):
        return ""
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        eid = str(ent.get("entity_id") or ent.get("id") or "").strip()
        lines.append(f"• {eid or '（未知实体）'}")
        for key, label in (
            ("location", "位置"),
            ("status", "状态"),
        ):
            val = str(ent.get(key) or "").strip()
            if val:
                lines.append(f"  {label}：{val}")
        for key, label in (
            ("knowledge", "新知"),
            ("possessions", "获得"),
            ("knowledge_remove", "遗忘"),
            ("possessions_remove", "失去"),
        ):
            items = ent.get(key) or []
            if isinstance(items, list) and items:
                lines.append(f"  {label}：{'；'.join(str(x) for x in items)}")
        rel = ent.get("relationships")
        if isinstance(rel, dict) and rel:
            parts = [f"{k}={v}" for k, v in rel.items()]
            lines.append(f"  关系：{'；'.join(parts)}")
    return "\n".join(lines).strip()


def _body_from_generic_json(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        return "\n".join(_fmt_list(data)).strip()
    if not isinstance(data, dict):
        return str(data)

    # Prefer well-known prose / summary fields.
    for key in (
        "text",
        "content",
        "body",
        "draft",
        "report",
        "arc",
        "summary",
        "recap",
        "story_so_far",
    ):
        val = data.get(key)
        if isinstance(val, str) and val.strip() and len(val.strip()) > 20:
            return val.strip()

    # Otherwise render a compact readable dump of top-level string/list fields.
    lines: list[str] = []
    for k, v in data.items():
        if k in {"usage", "model"}:
            continue
        if isinstance(v, str) and v.strip():
            lines.append(f"{k}：{v.strip()}")
        elif isinstance(v, list) and v:
            lines.append(f"{k}：")
            lines.extend(f"  {x}" for x in _fmt_list(v))
        elif isinstance(v, (int, float, bool)):
            lines.append(f"{k}：{v}")
    return "\n".join(lines).strip()


def extract_response_body(stage: str, response_text: str) -> dict[str, Any]:
    """Pull human-readable main content out of a raw model response.

    Returns ``{body, kind, is_json}`` where *kind* is ``prose`` or ``structured``.
    """
    text = (response_text or "").strip()
    if not text:
        return {"body": "", "kind": "prose", "is_json": False}

    parsed = _try_parse_json(text)
    if parsed is None:
        # Plain prose — strip wrapping fences if the whole blob is fenced.
        if text.startswith("```"):
            lines = text.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return {"body": text, "kind": "prose", "is_json": False}

    stage = (stage or "").strip()
    body = ""
    if stage == "checker" and isinstance(parsed, dict):
        body = _body_from_checker(parsed)
    elif stage == "planner" and isinstance(parsed, dict):
        body = _body_from_planner(parsed)
    elif stage == "enricher" and isinstance(parsed, dict):
        body = _body_from_enricher(parsed)
    elif stage == "threads" and isinstance(parsed, dict):
        body = _body_from_threads(parsed)
    elif stage == "entity_delta" and isinstance(parsed, dict):
        body = _body_from_entity_delta(parsed)
    else:
        body = _body_from_generic_json(parsed)

    if not body:
        body = json.dumps(parsed, ensure_ascii=False, indent=2, default=str)

    return {
        "body": body,
        "kind": "structured" if isinstance(parsed, (dict, list)) else "prose",
        "is_json": True,
    }


def _parse_usage(usage: Any) -> tuple[int, int, int] | None:
    """Return ``(prompt, completion, total)`` or ``None`` if missing."""
    if not isinstance(usage, dict):
        return None
    try:
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return None
    total_raw = usage.get("total_tokens")
    try:
        total = int(total_raw) if total_raw is not None else pt + ct
    except (TypeError, ValueError):
        total = pt + ct
    if pt == 0 and ct == 0 and total == 0 and total_raw is None:
        # Empty usage dict — treat as missing.
        if "prompt_tokens" not in usage and "completion_tokens" not in usage and "total_tokens" not in usage:
            return None
    return pt, ct, total


def _aggregate_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = completion = total = 0
    with_usage = 0
    for rec in records:
        parsed = _parse_usage(rec.get("usage"))
        if parsed is None:
            continue
        pt, ct, tt = parsed
        prompt += pt
        completion += ct
        total += tt
        with_usage += 1
    calls = len(records)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "calls": calls,
        "calls_with_usage": with_usage,
        "calls_missing_usage": max(0, calls - with_usage),
    }


def _iter_log_records(
    deps: ProjectDeps,
    *,
    date: str | None = None,
) -> list[dict[str, Any]]:
    if date:
        return _read_jsonl(_log_file(deps, date))
    root = _logs_root(deps)
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for f in sorted(root.glob("*.jsonl")):
        if _DATE_RE.match(f.stem):
            out.extend(_read_jsonl(f))
    return out


@router.get("/llm-logs/dates")
def list_llm_log_dates(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """List available log dates (newest first)."""
    root = _logs_root(deps)
    if not root.exists():
        return {"dates": []}
    dates: list[str] = []
    for f in sorted(root.glob("*.jsonl"), reverse=True):
        stem = f.stem
        if _DATE_RE.match(stem):
            dates.append(stem)
    return {"dates": dates}


@router.get("/llm-logs/usage")
def get_llm_log_usage(
    date: str | None = Query(None, description="可选，YYYY-MM-DD；省略则汇总全项目"),
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Aggregate prompt / completion / total tokens from trace logs."""
    if date:
        _validate_date(date)
    records = _iter_log_records(deps, date=date)
    usage = _aggregate_usage(records)
    return {"date": date, "scope": "day" if date else "project", **usage}


@router.get("/llm-logs")
def list_llm_logs(
    date: str = Query(..., description="YYYY-MM-DD"),
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Return truncated summaries for one day's traces, grouped by stage."""
    path = _log_file(deps, date)
    raw = _read_jsonl(path)
    entries = [_summarize(rec, i) for i, rec in enumerate(raw)]

    # Group by stage (preserve first-seen order, then sort groups by latest ts desc).
    groups_map: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        groups_map.setdefault(e["stage"], []).append(e)

    stage_counts = Counter(e["stage"] for e in entries)
    groups = [
        {
            "stage": stage,
            "count": stage_counts[stage],
            "entries": sorted(items, key=lambda x: x.get("ts") or "", reverse=True),
        }
        for stage, items in groups_map.items()
    ]
    groups.sort(
        key=lambda g: max((e.get("ts") or "") for e in g["entries"]) if g["entries"] else "",
        reverse=True,
    )

    return {
        "date": date,
        "total": len(entries),
        "groups": groups,
        "usage": _aggregate_usage(raw),
    }


@router.get("/llm-logs/entry")
def get_llm_log_entry(
    date: str = Query(..., description="YYYY-MM-DD"),
    index: int = Query(..., ge=0, description="0-based line index within the day file"),
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Return one full trace record for the detail drawer."""
    path = _log_file(deps, date)
    raw = _read_jsonl(path)
    if index >= len(raw):
        raise HTTPException(404, f"日志条目 #{index} 不存在")
    rec = raw[index]
    # Normalize prompt for the UI.
    prompt = rec.get("prompt") or []
    if not isinstance(prompt, list):
        prompt = [{"role": "raw", "content": str(prompt)}]

    response = rec.get("response")
    if isinstance(response, (dict, list)):
        response_text = json.dumps(response, ensure_ascii=False, indent=2, default=str)
    elif response is None:
        response_text = ""
    else:
        response_text = str(response)

    stage = str(rec.get("stage") or "unknown")
    extracted = extract_response_body(stage, response_text)

    return {
        "date": date,
        "index": index,
        "ts": rec.get("ts") or "",
        "started_at": rec.get("started_at") or "",
        "stage": stage,
        "project": rec.get("project") or "",
        "chapter": rec.get("chapter"),
        "model": rec.get("model") or "",
        "usage": rec.get("usage") if isinstance(rec.get("usage"), dict) else None,
        "error": rec.get("error"),
        "warnings": rec.get("warnings") if isinstance(rec.get("warnings"), list) else [],
        "resolved_ids": rec.get("resolved_ids") if isinstance(rec.get("resolved_ids"), dict) else {},
        "prompt": [
            {"role": m.get("role", ""), "content": str(m.get("content", ""))}
            if isinstance(m, dict)
            else {"role": "raw", "content": str(m)}
            for m in prompt
        ],
        "body": extracted["body"],
        "body_kind": extracted["kind"],
        "response_is_json": extracted["is_json"],
        "response": response_text,
        "meta": {
            k: v
            for k, v in rec.items()
            if k
            not in {
                "ts",
                "started_at",
                "stage",
                "project",
                "chapter",
                "model",
                "usage",
                "error",
                "warnings",
                "resolved_ids",
                "prompt",
                "response",
            }
        },
    }
