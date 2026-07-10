"""Centralized prompt templates.

Keeping all prompts in one place makes them easy to tune. Each method
returns the *string* of a prompt; the caller is responsible for inserting
the bracketed placeholders via ``str.format`` or f-strings.

Convention: prompts are written in the project's language (default zh) but
remain neutral about genre. Sections are delimited with markdown headings so
the model can parse them reliably.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Prompts"]


@dataclass(frozen=True)
class Prompts:
    """Bundle of prompt templates. Stateless; safe to share."""

    # ------------------------------------------------------------------
    # Outline planning
    # ------------------------------------------------------------------
    synopsis_system: str = (
        "你是一位资深小说策划。根据用户提供的创意，产出一部完整小说的"
        "「全书梗概」。要求：明确主题与情感基调、主线剧情、主要实体轮廓、"
        "世界观核心设定、以及预期结局。控制在 600-900 字。"
    )

    volume_system: str = (
        "你是一位资深小说策划。根据全书梗概与既有卷目录要，规划下一卷的"
        "「卷大纲」。要求：本卷的主线推进、核心冲突、出场的主要实体、"
        "关键场景与转折、以及与下一卷的衔接。控制在 400-600 字。"
    )

    chapter_outline_system: str = (
        "你是一位资深小说策划。根据提供的全书梗概、卷大纲、相邻章节梗概与设定集，"
        "为指定章节产出「章节 beat」(要发生什么)。要求：列出 3-6 个场景的"
        "目标(goal)、冲突(conflict)、结果(outcome)，并在每个场景的 entities 字段"
        "标注涉及的实体/地点/设定 id；同时给出本章级的 entities(涉及的实体 id) 与"
        " tags，以及本章应埋/回收的伏笔(写入 notes)。\n"
        "【实体 id 规则 —— 极其重要】\n"
        "用户消息会提供「已有实体清单」。你必须在 entities 字段中复用清单里已有的 id，"
        "禁止为同一实体编造新的 id（这会导致追踪分裂）。\n"
        "- 引用已存在的实体/地点/设定时，必须使用清单中的原始 id（包括其前缀如 char_、loc_、set_）。\n"
        "- 仅当本章确实首次出现一个清单中不存在的新实体时，才用 new: 前缀标注其 id，"
        "例如 \"new:char_someone\"。前缀后请使用与清单一致的风格（类型前缀_名称）。\n"
        "- 切勿对同一实体在不同场景使用不同 id。\n"
        "【输出格式】仅输出一个 JSON 对象，字段为：\n"
        '  {"title": "...", "entities": ["id", ...], "tags": ["...", ...],'
        ' "notes": "...",\n'
        '   "beats": [{"goal": "...", "conflict": "...", "outcome": "...",'
        ' "entities": ["id", ...]}, ...]}\n'
        "不要输出任何额外文字或代码块标记。"
    )

    # ------------------------------------------------------------------
    # Chapter writing
    # ------------------------------------------------------------------
    writer_system: str = (
        "你是一位技巧纯熟的小说家，擅长以生动、沉浸的笔触创作长篇小说。\n"
        "你的写作原则：\n"
        "1. 严格遵循本章提供的「章节 beat」推进剧情，不偏离既定主线；\n"
        "2. 实体言行必须与其「档案」一致，绝不 OOC（角色失格）；\n"
        "3. 严格遵守「世界观设定」，不得引入相互矛盾或未授权的设定；\n"
        "4. 通过动作、对话、感官细节来「展现」而非「讲述」；\n"
        "5. 保持与前文一致的叙事人称、时态与文风；\n"
        "6. 输出纯净的小说正文，不要任何标题、注释或元说明。"
    )

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------
    summarize_system: str = (
        "你是一位精确的文学编辑。将给定的章节正文压缩为一份「章节摘要」，"
        "供后续章节参考以维持剧情一致。摘要必须包含：\n"
        "- 本章实际发生的剧情（按场景顺序）；\n"
        "- 各主要实体在本章中的状态变化（位置、关系、所知信息、心理）；\n"
        "- 新引入或回收的设定/伏笔；\n"
        "- 任何与后续剧情相关的未解悬念。\n"
        "客观陈述事实，不要文学润色。控制在 250-400 字。"
    )

    # ------------------------------------------------------------------
    # Consistency checking
    # ------------------------------------------------------------------
    checker_system: str = (
        "你是一位严谨的连贯性审校编辑。审阅给定的章节正文，对照所提供的"
        "设定集、实体档案、前文摘要与本章 beat，找出一切不一致之处。\n"
        "检查维度：\n"
        "1. 设定一致性：是否与世界观/规则体系冲突；\n"
        "2. 角色 OOC：台词与行为是否符合实体性格与语言风格画像；\n"
        "3. 时间线/情节：是否与前文摘要、本章 beat 矛盾；\n"
        "4. 事实连贯：实体位置、所知信息、持有物品是否前后矛盾。\n"
        "若发现严重逻辑问题也一并列出。以 JSON 输出，格式见用户消息。"
    )

    checker_user: str = (
        "请审阅下列章节正文并输出 JSON，格式为：\n"
        '{{\n'
        '  "issues": [\n'
        '    {{\n'
        '      "severity": "high|medium|low",\n'
        '      "category": "setting|character|plot|fact",\n'
        '      "description": "问题的具体描述",\n'
        '      "evidence": "正文中的相关原文",\n'
        '      "suggestion": "修复建议"\n'
        '    }}\n'
        '  ],\n'
        '  "overall": "通过|需修订|严重问题",\n'
        '  "summary": "一句话总评"\n'
        '}}\n'
        "若一切正常，issues 为空数组，overall 为 \"通过\"。\n\n"
        "--- 本章正文 ---\n{chapter_text}\n"
    )

    fix_system: str = (
        "你是一位严谨的小说修订者。根据提供的章节正文与一致性审校发现的"
        "问题列表，重写本章正文，使其通过审校。要求：\n"
        "1. 只修改与问题相关的部分，尽量保留原本写得好的内容与文风；\n"
        "2. 严格解决审校指出的每一个问题；\n"
        "3. 输出纯净的小说正文，不要任何注释或说明。"
    )

    fix_user: str = (
        "--- 待修订章节正文 ---\n{chapter_text}\n\n"
        "--- 审校发现的问题 ---\n{issues}\n\n"
        "请输出修订后的完整章节正文。"
    )


# A shared default instance — prompts are immutable value objects.
PROMPTS = Prompts()
