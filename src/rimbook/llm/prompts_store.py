"""Prompt template catalog, workspace overrides, and preview rendering.

All prompt templates live on the :class:`~rimbook.llm.prompts.Prompts`
dataclass. This module provides:

* :data:`PROMPT_META` — per-field metadata (stage, role, description, the
  placeholders each template expects and where the runtime value comes from,
  and whether the field is actually used by the pipeline).
* :func:`load_prompts` — build a :class:`Prompts` instance for a workspace,
  applying user overrides stored in ``<workspace>/prompts.yaml``.
* :func:`save_prompts_overrides` / :func:`list_overrides` / :func:`reset_all`
  — manage the override file on disk.
* :func:`render_preview` — fill a template's placeholders with real data for
  one chapter so the user can see exactly what will be sent to the LLM.

The override file is a flat ``{key: value}`` map; any key absent from it falls
back to the in-code default. Editing prompts does not modify source files.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Iterable

import yaml

from .prompts import Prompts

__all__ = [
    "PROMPT_META",
    "PROMPT_KEYS",
    "PROMPT_OVERRIDES_FILENAME",
    "default_prompts_dict",
    "load_prompts",
    "load_default_prompts",
    "list_overrides",
    "save_prompts_overrides",
    "reset_all_overrides",
    "render_preview",
]

PROMPT_OVERRIDES_FILENAME = "prompts.yaml"

# Stage labels (also used by the frontend to group the prompt list).
STAGE_PLANNING = "planning"
STAGE_WRITING = "writing"
STAGE_SUMMARIZATION = "summarization"
STAGE_CHECKING = "checking"
STAGE_ENRICHMENT = "enrichment"

# Canonical order of fields as declared on Prompts.
PROMPT_KEYS: list[str] = [f.name for f in fields(Prompts)]


def _ph(name: str, desc: str, source: str) -> dict[str, str]:
    return {"name": name, "desc": desc, "source": source}


# Per-field metadata catalog. `placeholders` lists every {name} the template
# expects; the pipeline fills them via str.format. `source` describes, in
# human terms, where the runtime value comes from.
PROMPT_META: dict[str, dict[str, Any]] = {
    "synopsis_system": {
        "stage": STAGE_PLANNING,
        "role": "system",
        "zh_name": "全书梗概 · 系统",
        "zh_module": "全书梗概",
        "description": "生成「全书梗概」时给 LLM 的系统提示：定位资深小说策划，"
        "要求产出主题/主线/实体轮廓/世界观/结局，600-900 字。",
        "placeholders": [],
        "in_use": True,
    },
    "synopsis_user": {
        "stage": STAGE_PLANNING,
        "role": "user",
        "zh_name": "全书梗概 · 用户",
        "zh_module": "全书梗概",
        "description": "生成全书梗概时的用户消息，把用户输入的创意 premise 交给 LLM。",
        "placeholders": [_ph("premise", "用户提供的小说创意", "用户在「大纲」页输入")],
        "in_use": True,
    },
    "volume_system": {
        "stage": STAGE_PLANNING,
        "role": "system",
        "zh_name": "卷大纲 · 系统",
        "zh_module": "卷大纲",
        "description": "规划「卷大纲」时的系统提示：定位资深小说策划，400-600 字。",
        "placeholders": [],
        "in_use": True,
    },
    "volume_user": {
        "stage": STAGE_PLANNING,
        "role": "user",
        "zh_name": "卷大纲 · 用户",
        "zh_module": "卷大纲",
        "description": "规划某一卷的用户消息，注入全书梗概、已有卷目与卷号/标题。",
        "placeholders": [
            _ph("synopsis", "全书梗概", "outline.read_synopsis()"),
            _ph("existing_desc", "已规划的卷目列表", "outline.list_volumes() 格式化"),
            _ph("number", "本卷序号", "用户指定的卷号"),
            _ph("title_hint", "可能的标题注脚（形如“（标题：xx）”，无则空）", "卷标题"),
        ],
        "in_use": True,
    },
    "chapter_outline_system": {
        "stage": STAGE_PLANNING,
        "role": "system",
        "zh_name": "章节 beat · 系统",
        "zh_module": "章节 beat",
        "description": "规划章节 beat 时的系统提示，定义 entities id 复用规则、"
        "JSON 输出格式（title/entities/tags/notes/beats[]）。",
        "placeholders": [],
        "in_use": True,
    },
    "chapter_outline_user": {
        "stage": STAGE_PLANNING,
        "role": "user",
        "zh_name": "章节 beat · 用户",
        "zh_module": "章节 beat",
        "description": "规划章节 beat 的用户消息，注入梗概/卷大纲/近几章/实体清单/"
        "作者提示/章号/标题。各 block 占位符已含标题行或为空，可整段编辑。",
        "placeholders": [
            _ph("synopsis", "全书梗概", "outline.read_synopsis()"),
            _ph("volume_arc_block", "本卷大纲块（含“本卷大纲：”标题行，无则空）", "outline.read_volume()"),
            _ph("prev_desc_block", "近几章梗概块（含标题行，无则空）", "outline.list_chapters() 最近3章"),
            _ph("entity_registry_block", "已有实体清单块（含标题行，无则空）", "codex.iter_all()"),
            _ph("hint_block", "作者提示块（含“作者提示：”标题行，无则空）", "用户 hint 参数"),
            _ph("number", "本章序号", "章节号"),
            _ph("title_block", "标题注脚（“标题：xx”，无则空）", "章节标题"),
        ],
        "in_use": True,
    },
    "writer_system": {
        "stage": STAGE_WRITING,
        "role": "system",
        "zh_name": "章节写作 · 系统",
        "zh_module": "章节写作",
        "description": "撰写章节正文时的系统提示：小说家 persona 与六条写作原则"
        "（遵循 beat、不 OOC、世界观一致、展现而非讲述、人称时态连贯、纯净正文）。",
        "placeholders": [],
        "in_use": True,
    },
    "writer_user": {
        "stage": STAGE_WRITING,
        "role": "user",
        "zh_name": "章节写作 · 用户",
        "zh_module": "章节写作",
        "description": "撰写章节正文的用户消息，把结构化上下文（设定集/摘要/状态/"
        "前文/本章 beat）与章号交给 LLM。",
        "placeholders": [
            _ph("number", "本章序号", "章节号"),
            _ph("context", "由 ContextAssembler 组装好的结构化上下文全文", "assembler.assemble_for_chapter()"),
        ],
        "in_use": True,
    },
    "writer_revise_user": {
        "stage": STAGE_WRITING,
        "role": "user",
        "zh_name": "章节修订 · 用户",
        "zh_module": "章节修订",
        "description": "修订章节正文的用户消息，注入上下文、当前草稿与修订要求"
        "（被自动修复与手动修订共用）。",
        "placeholders": [
            _ph("number", "本章序号", "章节号"),
            _ph("context", "结构化上下文全文", "assembler.assemble_for_chapter()"),
            _ph("draft_text", "当前章节草稿正文", "drafts/ch<N>.md"),
            _ph("instructions", "修订要求（由审校问题摘要或用户给出）", "checker 自动修复 / 用户指令"),
        ],
        "in_use": True,
    },
    "summarize_system": {
        "stage": STAGE_SUMMARIZATION,
        "role": "system",
        "zh_name": "章节摘要 · 系统",
        "zh_module": "章节摘要",
        "description": "生成章节摘要时的系统提示，要求 250-400 字客观摘要。",
        "placeholders": [],
        "in_use": True,
    },
    "summarize_user": {
        "stage": STAGE_SUMMARIZATION,
        "role": "user",
        "zh_name": "章节摘要 · 用户",
        "zh_module": "章节摘要",
        "description": "生成章节摘要的用户消息，注入章号与章节正文。",
        "placeholders": [
            _ph("chapter_number", "本章序号", "章节号"),
            _ph("chapter_text", "本章草稿正文", "drafts/ch<N>.md"),
        ],
        "in_use": True,
    },
    "entity_delta_system": {
        "stage": STAGE_SUMMARIZATION,
        "role": "system",
        "zh_name": "实体状态增量 · 系统",
        "zh_module": "实体状态增量",
        "description": "抽取实体状态增量的系统提示：定义 location/status 覆盖、"
        "knowledge/possessions 增删、relationships 增删的生命周期规则。",
        "placeholders": [],
        "in_use": True,
    },
    "entity_delta_user": {
        "stage": STAGE_SUMMARIZATION,
        "role": "user",
        "zh_name": "实体状态增量 · 用户",
        "zh_module": "实体状态增量",
        "description": "抽取实体状态增量的用户消息，注入正文、章号与待跟踪实体 id，"
        "并约定 JSON 输出格式。",
        "placeholders": [
            _ph("chapter_number", "本章序号", "章节号"),
            _ph("chapter_text", "本章草稿正文", "drafts/ch<N>.md"),
            _ph("entity_ids", "本章涉及的实体 id 列表", "chapter.all_entities()"),
        ],
        "in_use": True,
    },
    "checker_system": {
        "stage": STAGE_CHECKING,
        "role": "system",
        "zh_name": "一致性审校 · 系统",
        "zh_module": "一致性审校",
        "description": "一致性审校的系统提示，检查设定/角色 OOC/时间线情节/事实连贯四维。",
        "placeholders": [],
        "in_use": True,
    },
    "checker_user": {
        "stage": STAGE_CHECKING,
        "role": "user",
        "zh_name": "一致性审校 · 用户",
        "zh_module": "一致性审校",
        "description": "一致性审校的用户消息，约定 issues[]/overall/summary 的 JSON 输出格式，"
        "并附本章正文。注意 JSON 花括号已用 {{ }} 转义。",
        "placeholders": [
            _ph("chapter_text", "本章草稿正文", "drafts/ch<N>.md"),
        ],
        "in_use": True,
    },
    "fix_system": {
        "stage": STAGE_CHECKING,
        "role": "system",
        "zh_name": "自动修复（未使用） · 系统",
        "zh_module": "自动修复（未使用）",
        "description": "（保留字段，当前未被流水线使用）自动修复的系统提示。",
        "placeholders": [],
        "in_use": False,
    },
    "fix_user": {
        "stage": STAGE_CHECKING,
        "role": "user",
        "zh_name": "自动修复（未使用） · 用户",
        "zh_module": "自动修复（未使用）",
        "description": "（保留字段，当前未被流水线使用）自动修复的用户消息，"
        "注入待修订正文与审校问题。",
        "placeholders": [
            _ph("chapter_text", "本章草稿正文", "drafts/ch<N>.md"),
            _ph("issues", "审校发现的问题列表", "checker 输出"),
        ],
        "in_use": False,
    },
    "codex_enrich_system": {
        "stage": STAGE_ENRICHMENT,
        "role": "system",
        "zh_name": "设定档案充实 · 系统",
        "zh_module": "设定档案充实",
        "description": "设定档案充实的系统提示：定义新实体发现、已有档案追加揭示、"
        "矛盾提醒三项任务，以及 new_entities/updates/summary 的 JSON 输出契约。",
        "placeholders": [],
        "in_use": True,
    },
    "codex_enrich_user": {
        "stage": STAGE_ENRICHMENT,
        "role": "user",
        "zh_name": "设定档案充实 · 用户",
        "zh_module": "设定档案充实",
        "description": "设定档案充实的用户消息，注入章号、本章正文（截断）与已有实体档案。",
        "placeholders": [
            _ph("chapter_number", "本章序号", "章节号"),
            _ph("chapter_text", "本章草稿正文（截断至 16384 字符）", "drafts/ch<N>.md"),
            _ph("existing_codex", "已有的实体清单文本", "codex.iter_all() 格式化"),
        ],
        "in_use": True,
    },
}


def default_prompts_dict() -> dict[str, str]:
    """Snapshot of the prompt defaults as a plain dict."""
    return {k: getattr(Prompts(), k) for k in PROMPT_KEYS}


def load_default_prompts() -> Prompts:
    """A fresh Prompts instance with no overrides applied."""
    return Prompts()


def _overrides_path(workspace: Path) -> Path:
    return workspace / PROMPT_OVERRIDES_FILENAME


def _load_overrides(workspace: Path) -> dict[str, str]:
    path = _overrides_path(workspace)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if k in PROMPT_KEYS and isinstance(v, str):
            out[k] = v
    return out


def load_prompts(workspace: Path) -> Prompts:
    """Build a Prompts instance, applying workspace overrides on top of defaults."""
    p = load_default_prompts()
    for k, v in _load_overrides(workspace).items():
        setattr(p, k, v)
    return p


def list_overrides(workspace: Path) -> dict[str, str]:
    return _load_overrides(workspace)


def save_prompts_overrides(workspace: Path, overrides: dict[str, str]) -> Path:
    path = _overrides_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Prompt template overrides for this RimBook workspace.\n"
        "# Lines omitted here fall back to the in-code defaults.\n"
        + yaml.safe_dump(overrides, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    return path


def reset_all_overrides(workspace: Path) -> None:
    path = _overrides_path(workspace)
    if path.exists():
        path.unlink()


def catalog(workspace: Path | None = None) -> list[dict[str, Any]]:
    """Return a serializable list describing every prompt with current values.

    `value` reflects the effective value (override if present, else default).
    Setting *workspace* enables the `overridden` flag via the override file.
    """
    overrides = _load_overrides(workspace) if workspace is not None else {}
    defaults = default_prompts_dict()
    out: list[dict[str, Any]] = []
    for key in PROMPT_KEYS:
        meta = dict(PROMPT_META.get(key, {}))
        overridden = key in overrides
        out.append(
            {
                "key": key,
                "stage": meta.get("stage"),
                "role": meta.get("role"),
                "zh_name": meta.get("zh_name", key),
                "zh_module": meta.get("zh_module", key),
                "description": meta.get("description", ""),
                "placeholders": meta.get("placeholders", []),
                "in_use": meta.get("in_use", True),
                "default_value": defaults[key],
                "value": overrides.get(key, defaults[key]),
                "overridden": overridden,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Preview rendering — fill a template's placeholders with real chapter data.
# ---------------------------------------------------------------------------


def _format_entity_ids(ids: Iterable[str]) -> str:
    return str(list(ids))


def render_preview(
    prompts: Prompts,
    key: str,
    *,
    outline,
    assembler,
    codex,
    paths,
    number: int = 1,
    premise: str = "",
    instructions: str = "",
) -> str:
    """Render *key* with real data for chapter *number*.

    All pipeline dependencies are passed in so this stays read-only and does
    not require a full ProjectDeps. Unknown placeholder usage is tolerated:
    we pass a superset of kwargs to str.format with `format_map` of a default
    dict so missing-but-referenced placeholders degrade to the raw name.
    """
    if key not in PROMPT_KEYS:
        raise KeyError(key)
    template = getattr(prompts, key)
    meta = PROMPT_META.get(key, {})
    required = {p["name"] for p in meta.get("placeholders", [])}

    # Gather possibly-needed runtime values; absence of a dependency simply
    # leaves them blank.
    chapter = None
    if outline is not None:
        try:
            chapter = outline.read_chapter(number)
        except Exception:
            chapter = None

    chapter_text = ""
    if paths is not None:
        try:
            p = paths.draft_file(number)
            if p.exists():
                chapter_text = p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if not chapter_text and chapter is not None:
        # Fall back: build a readable beat text as a stand-in.
        chapter_text = _chapter_to_text(chapter)

    context_text = ""
    if assembler is not None and chapter is not None:
        try:
            context_text = assembler.assemble_for_chapter(chapter).text
        except Exception:
            context_text = ""

    synopsis = ""
    if outline is not None:
        try:
            synopsis = outline.read_synopsis().strip()
        except Exception:
            synopsis = ""

    volume_arc_block = ""
    prev_desc_block = ""
    entity_registry_block = ""
    hint_block = ""
    title_block = ""
    number_str = str(number)
    if chapter is not None:
        if chapter.volume is not None and outline is not None:
            try:
                vol = outline.read_volume(chapter.volume)
                if vol and vol.arc.strip():
                    volume_arc_block = f"本卷大纲：\n{vol.arc.strip()}\n\n"
            except Exception:
                pass
        try:
            prevs = [c for c in outline.list_chapters() if c.number < number]
            prev_desc = _format_prev_chapters(prevs[-3:])
            if prev_desc:
                prev_desc_block = f"近几章梗概：\n{prev_desc}\n\n"
        except Exception:
            pass
        if codex is not None:
            registry = _format_entity_registry(codex)
            if registry:
                entity_registry_block = f"{registry}\n\n"
        title_block = f"标题：{chapter.title}" if chapter.title else ""

    entity_ids = list(chapter.all_entities()) if chapter is not None else []

    existing_codex = ""
    if codex is not None:
        existing_codex = _format_existing_codex(codex)

    kwargs: dict[str, Any] = {
        "premise": premise,
        "synopsis": synopsis,
        "existing_desc": "",
        "number": number_str,
        "title_hint": "",
        "volume_arc_block": volume_arc_block,
        "prev_desc_block": prev_desc_block,
        "entity_registry_block": entity_registry_block,
        "hint_block": hint_block,
        "title_block": title_block,
        "context": context_text,
        "draft_text": chapter_text,
        "instructions": instructions,
        "chapter_number": number_str,
        "chapter_text": chapter_text,
        "entity_ids": _format_entity_ids(entity_ids),
        "existing_codex": existing_codex,
        "issues": "（占位示例：审校发现的问题列表）",
    }
    # Fill volume-specific helpers if requested.
    if outline is not None and ("existing_desc" in required or "title_hint" in required):
        try:
            vols = outline.list_volumes()
        except Exception:
            vols = []
        from ..pipeline.planner import _format_existing_volumes  # local import avoids cycles
        kwargs["existing_desc"] = _format_existing_volumes(vols) or "（无）"
        kwargs["title_hint"] = ""

    return _safe_format(template, kwargs)


class _DefaultDict(dict):
    """A dict that yields the literal ``{key}`` for missing entries."""

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return "{" + key + "}"


def _safe_format(template: str, mapping: dict[str, Any]) -> str:
    """str.format that tolerates unknown placeholders (kept verbatim)."""
    return template.format_map(_DefaultDict(mapping))


def _chapter_to_text(chapter) -> str:
    lines = [f"第 {chapter.number} 章"]
    if chapter.title:
        lines.append(f"标题：{chapter.title}")
    if chapter.notes:
        lines.append(f"备注：{chapter.notes}")
    for i, b in enumerate(chapter.beats, start=1):
        lines.append(f"\n场景 {i}：")
        lines.append(f"  目标：{b.goal}")
        lines.append(f"  冲突：{b.conflict}")
        lines.append(f"  结果：{b.outcome}")
        if b.entities:
            lines.append(f"  实体：{', '.join(b.entities)}")
    return "\n".join(lines)


def _format_prev_chapters(chapters) -> str:
    if not chapters:
        return ""
    lines = []
    for c in chapters:
        title = f"「{c.title}」" if c.title else ""
        summ = c.summary or "（无摘要）"
        lines.append(f"- 第 {c.number} 章{title}：{summ}")
    return "\n".join(lines)


def _format_entity_registry(codex) -> str:
    try:
        entries = list(codex.iter_all())
    except Exception:
        return ""
    if not entries:
        return ""
    lines = ["已有实体清单（entities 字段必须复用这里的 id，新实体才用 new: 前缀）："]
    for e in entries:
        alias_str = f"（别名：{'、'.join(e.aliases)}）" if e.aliases else ""
        lines.append(f"  - {e.id}：{e.name}{alias_str}  [{e.type}]")
    return "\n".join(lines)


def _format_existing_codex(codex) -> str:
    try:
        entries = list(codex.iter_all())
    except Exception:
        return "（暂无实体档案）"
    if not entries:
        return "（暂无实体档案）"
    lines = []
    for e in entries:
        lines.append(f"## {e.id}（{e.type}）{e.name}")
        if e.aliases:
            lines.append(f"别名：{'、'.join(e.aliases)}")
        if e.tags:
            lines.append(f"标签：{', '.join(e.tags)}")
        body = (e.body or "").strip()
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()