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


@dataclass
class Prompts:
    """Bundle of prompt templates.

    Mutable so workspace-level overrides can be applied via
    :mod:`rimbook.llm.prompts_store`; the in-process instance is shared per
    project and not mutated after wiring.
    """

    # ------------------------------------------------------------------
    # Outline planning
    # ------------------------------------------------------------------
    synopsis_system: str = (
        "你是一位资深小说策划。根据用户提供的创意，产出一部完整小说的"
        "「全书梗概」。要求：明确主题与情感基调、主线剧情、主要实体轮廓、"
        "世界观核心设定、以及预期结局。控制在 600-900 字。"
    )

    synopsis_user: str = "请根据以下创意，撰写全书梗概：\n\n{premise}\n"

    volume_system: str = (
        "你是一位资深小说策划。根据全书梗概与既有卷目录要，规划下一卷的"
        "「卷大纲」。要求：本卷的主线推进、核心冲突、出场的主要实体、"
        "关键场景与转折、以及与下一卷的衔接。控制在 400-600 字。"
    )

    volume_user: str = (
        "全书梗概：\n{synopsis}\n\n"
        "已有卷目：\n{existing_desc}\n\n"
        "请规划第 {number} 卷{title_hint}。"
    )

    chapter_outline_system: str = (
        "你是一位资深小说策划。根据提供的全书梗概、卷大纲、相邻章节梗概与设定集，"
        "为指定章节产出「章节 beat」(要发生什么)。要求：列出 3-6 个场景的"
        "目标(goal)、冲突(conflict)、结果(outcome)，并在每个场景的 entities 字段"
        "标注涉及的实体/地点/设定 id；同时给出本章级的 entities(涉及的实体 id) 与"
        " tags，以及本章应埋/回收的伏笔(写入 notes)。\n"
        "【节奏与结构 —— 重要】同时给出：\n"
        "- purpose：本章的叙事功能（推进主线/塑造角色/铺垫/转折/喘息等，一句话）；\n"
        "- value_shift：本章的情感价值转变（如 \"希望→绝望\"、\"孤立→结盟\"）；\n"
        "- tension：张力等级（1-5 整数）。参考近几章的张力序列，形成起伏，"
        "避免连续多章同一强度；\n"
        "- hook：章末钩子（结尾应留下的悬念、转折或未答之问）；\n"
        "- story_date：本章故事内时间点（如 \"第3日黄昏\"、\"冬月初五\"），"
        "与 elapsed：距上一章经过的时间（如 \"半日\"、\"三天\"）。必须与上一章的"
        "时间点保持先后顺序一致。\n"
        "【情节线索】若用户消息提供了「未回收的情节线索」，请在规划时明确本章"
        "推进或回收哪些线索（写入 notes），不要让线索长期悬置或被遗忘。\n"
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
        '   "purpose": "...", "value_shift": "...", "tension": 3, "hook": "...",\n'
        '   "story_date": "...", "elapsed": "...",\n'
        '   "beats": [{"goal": "...", "conflict": "...", "outcome": "...",'
        ' "entities": ["id", ...]}, ...]}\n'
        "不要输出任何额外文字或代码块标记。"
    )

    chapter_outline_user: str = (
        "全书梗概：\n{synopsis}\n\n"
        "{volume_arc_block}"
        "{prev_desc_block}"
        "{open_threads_block}"
        "{entity_registry_block}"
        "{hint_block}"
        "请为第 {number} 章生成章节 beat。{title_block}"
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
        "5. 保持与前文一致的叙事人称、时态与文风；若上下文提供了「写作风格指南」，"
        "其中的人称/视角/语言基调/禁忌规则具有最高优先级，必须逐条遵守；\n"
        "6. 输出纯净的小说正文，不要任何标题、注释或元说明。"
    )

    writer_user: str = (
        "请根据以下结构化上下文，撰写第 {number} 章的完整正文。\n\n"
        "{context}\n\n"
        "现在请直接开始写正文。"
    )

    writer_revise_user: str = (
        "请根据以下结构化上下文，修订第 {number} 章的正文。\n\n"
        "{context}\n\n"
        "--- 当前正文 ---\n{draft_text}\n"
        "--- 修订要求 ---\n{instructions}\n"
        "请输出修订后的完整正文。"
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

    summarize_user: str = (
        "这是第 {chapter_number} 章的正文，请生成章节摘要。\n\n"
        "---\n{chapter_text}\n"
    )

    entity_delta_system: str = (
        "你是精确的小说状态跟踪助手。阅读章节正文，针对每个指定实体，"
        "判断其在『本章之后』的当前状态变化，并输出 JSON。\n"
        "只包含发生了变化或需要记录的字段；未变化的字段省略或留空。\n"
        "【生命周期规则 —— 重要】\n"
        "- knowledge/possessions 表示『本章新获得』的信息/物品；\n"
        "- knowledge_remove/possessions_remove 表示『本章遗忘/丢失』的信息/物品；\n"
        "- relationships 为 {{对方id: 关系简述}}；若关系终结/破裂，将值设为 null；\n"
        "- location/status 为本章结束时的最新值（会覆盖前值）。\n"
        "角色丢失物品、遗忘信息、关系破裂都必须如实记录到对应的 remove / null 字段。"
    )

    entity_delta_user: str = (
        "第 {chapter_number} 章正文：\n---\n{chapter_text}\n---\n\n"
        "需要跟踪的实体 id：{entity_ids}\n\n"
        "请输出 JSON，格式为：\n"
        '{{\n'
        '  "entities": [\n'
        '    {{\n'
        '      "entity_id": "...",\n'
        '      "location": "...",\n'
        '      "status": "...",\n'
        '      "knowledge": ["新获得的信息"],\n'
        '      "possessions": ["新获得的物品"],\n'
        '      "knowledge_remove": ["遗忘/过时的信息"],\n'
        '      "possessions_remove": ["丢失/消耗的物品"],\n'
        '      "relationships": {{"id": "关系", "结束的id": null}}\n'
        '    }}\n'
        '  ]\n'
        '}}\n'
        "只输出 JSON。"
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
        "以下是审校所需的参照材料（设定档案、实体当前状态、前文摘要、本章 beat 等），"
        "请以这些材料为准进行对照检查：\n\n"
        "{context}\n\n"
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

    # ------------------------------------------------------------------
    # Codex enrichment (post-write pipeline)
    # ------------------------------------------------------------------
    codex_enrich_system: str = (
        "你是小说设定档案分析师。你的任务是阅读一个章节的正文，对照已有的实体档案"
        "（人物、地点、势力、物品、世界观等），完成三件事：\n\n"
        "1. **发现新实体**：找出正文中首次出现、但在「已有实体档案」中不存在的实体"
        "（包括人物、地点、势力、重要物品、世界观概念）。为每个新实体生成一份完整档案。\n"
        "2. **充实已有档案**：对已在档案中的实体，找出本章**首次揭示**的新信息"
        "（外貌细节、性格特点、能力、动机、背景、关系变化等），生成追加片段。\n"
        "3. **矛盾提醒**：如果正文与已有档案直接矛盾（如档案写蓝色眼睛、正文写棕色），"
        "标记出来但不要修改档案正文。\n\n"
        "【档案撰写要求】\n"
        "- 使用中文撰写，内容丰富、信息密度高\n"
        "- 实体名称使用正文中出现的中文名，不要用拼音或英文\n"
        "- 人物档案必须包含：外貌、性格、语言风格（说话方式/口癖/用词特征）、背景、动机\n"
        "- 地点档案必须包含：位置、环境氛围、功能、特殊之处\n"
        "- 只记录正文中**确实出现或明确暗示**的信息，不要编造\n"
        "- 追加片段前标注来源章节，格式为「第N章揭示：…」\n"
        "- **每个 new_entities 条目必须包含至少一条 revelations**，记录该实体在本章首次登场的关键信息\n"
        "【输出格式】仅输出一个 JSON 对象：\n"
        '{\n'
        '  "new_entities": [\n'
        '    {\n'
        '      "id": "char_xxx|loc_xxx|faction_xxx|item_xxx|set_xxx|evt_xxx",\n'
        '      "name": "实体中文名",\n'
        '      "type": "character|location|faction|item|worldbuilding|timeline",\n'
        '      "aliases": ["别名1", "别名2"],\n'
        '      "tags": ["标签1", "标签2"],\n'
        '      "body": "完整档案正文（Markdown格式）",\n'
        '      "revelations": [\n'
        '        {"content": "首次登场/引入时的关键信息（1-3句话，必填）", "source": "正文中的证据片段"}\n'
        '      ]\n'
        '    }\n'
        '  ],\n'
        '  "updates": [\n'
        '    {\n'
        '      "id": "已有实体的id",\n'
        '      "revelations": [\n'
        '        {"content": "本章新揭示的信息（1-3句话）", "source": "正文中的证据片段"}\n'
        '      ],\n'
        '      "contradictions": [\n'
        '        {"description": "矛盾描述", "evidence": "正文证据"}\n'
        '      ]\n'
        '    }\n'
        '  ],\n'
        '  "summary": "一句话总结本次变更"\n'
        '}\n'
        "如果没有新实体或更新，对应字段留空数组。不要输出额外文字。\n"
        "【防重复 —— 极其重要】\n"
        "判定一个实体是否「新」的唯一依据是：它是否已出现在你被提供的「已有实体档案」中，"
        "哪怕已有档案的 id 与你设想的不同（例如不同前缀、拼音/英文下划线差异、不同别名）。"
        "若该实体已在已有档案中存在（无论你建议什么 id），**禁止**在 new_entities 中再创建它；"
        "必须改放到 updates 中，并通过 revelations 增补新信息。"
        "重复创建同一实体会导致追踪分裂与档案重复，是必须避免的错误。"
    )

    codex_enrich_user: str = (
        "--- 第 {chapter_number} 章正文 ---\n"
        "{chapter_text}\n\n"
        "--- 已有实体档案 ---\n"
        "{existing_codex}\n\n"
        "{planned_new_block}\n"
        "请分析本章正文，发现新实体并生成档案，对已有实体补充新揭示。\n"
        "若上面给出了「本章规划阶段已分配实体 id」，必须优先复用其中的 id 给正文里同一实体建档案（即便你给的中文名不同）；"
        "禁止对这些规划阶段已分配的实体改用别的 id。其余无 id 提示的新实体仍可参照 type 前缀风格起名，但应优先复用已有档案 id。"
    )

    # ------------------------------------------------------------------
    # Style bible (voice card)
    # ------------------------------------------------------------------
    style_generate_system: str = (
        "你是一位资深文学编辑。阅读给定的小说章节样本，提炼出一份「写作风格指南」"
        "（style bible），供后续章节保持文风一致。指南必须包含：\n"
        "1. 叙事人称与视角规则（第几人称、单/多视角、视角切换规则）；\n"
        "2. 时态与叙事距离；\n"
        "3. 语言基调（冷峻/华丽/口语化/古雅等）与句式偏好（长短句节奏、段落密度）；\n"
        "4. 对话风格（对话与叙述的比例、是否使用方言/口癖）；\n"
        "5. 禁忌清单（应避免的词汇、腔调、修辞，如陈词滥调、翻译腔）；\n"
        "6. 一到两段最能代表该文风的示例段落（从样本中摘录）。\n"
        "以 Markdown 输出，条目清晰，可被后续写作直接遵循。控制在 500-800 字。"
    )

    style_generate_user: str = (
        "小说标题：{title}\n\n"
        "以下是已写章节的样本，请据此提炼写作风格指南：\n\n"
        "{samples}\n"
    )

    # ------------------------------------------------------------------
    # Hierarchical memory: volume recap + story-so-far
    # ------------------------------------------------------------------
    volume_recap_system: str = (
        "你是一位精确的文学编辑。将给定的一卷各章摘要压缩为一份「卷情节回顾」，"
        "供后续写作参考。要求：\n"
        "- 按时间顺序概括本卷实际发生的主线剧情与关键转折；\n"
        "- 记录卷末各主要实体的处境（位置、关系、目标）；\n"
        "- 列出本卷埋下但尚未回收的伏笔/悬念；\n"
        "- 客观陈述，不要文学润色。控制在 400-600 字。"
    )

    volume_recap_user: str = (
        "第 {volume_number} 卷《{volume_title}》各章摘要：\n\n"
        "{chapter_summaries}\n\n"
        "请生成本卷的情节回顾。"
    )

    story_so_far_system: str = (
        "你是一位精确的文学编辑。维护一份「全书至今」故事线：以最凝练的篇幅概括"
        "小说开篇至今实际发生的剧情，供写作后续章节时作为长程记忆。要求：\n"
        "- 以「已有故事线」为基础增量改写，融入「新增章节摘要」的内容；\n"
        "- 越早的剧情压缩得越狠，最近的剧情保留更多细节；\n"
        "- 保留：主线进展、重大转折、主要实体的关系与目标变化、未解悬念；\n"
        "- 客观陈述事实，不要文学润色。控制在 600-1000 字。"
    )

    story_so_far_user: str = (
        "已有故事线（截至第 {prev_upto} 章）：\n{previous}\n\n"
        "新增章节摘要：\n{new_summaries}\n\n"
        "请输出更新后的「全书至今」故事线（截至第 {upto} 章）。"
    )

    # ------------------------------------------------------------------
    # Plot thread ledger (foreshadowing / suspense / promises)
    # ------------------------------------------------------------------
    thread_extract_system: str = (
        "你是精确的小说情节线索跟踪助手。阅读章节正文，对照「当前未回收的线索清单」，"
        "找出本章：\n"
        "1. 新埋下的线索（伏笔 foreshadow / 悬念 suspense / 对读者的承诺 promise）；\n"
        "2. 推进了的已有线索（有新进展但未完结）；\n"
        "3. 回收/兑现了的已有线索。\n"
        "【规则】\n"
        "- 已有线索必须复用清单中的 id，禁止为同一线索新建 id；\n"
        "- 只记录对后续剧情有意义的线索，不要把普通剧情事件都当线索；\n"
        "- expected_resolve_chapter 为预计回收的章号，不确定则为 null。\n"
        "【输出格式】仅输出一个 JSON 对象：\n"
        '{\n'
        '  "new_threads": [\n'
        '    {"id": "thread_xxx（英文 slug）", "description": "线索内容",\n'
        '     "type": "foreshadow|suspense|promise",\n'
        '     "expected_resolve_chapter": null, "note": "本章如何埋下"}\n'
        '  ],\n'
        '  "progressed": [{"id": "已有线索id", "note": "本章的进展"}],\n'
        '  "resolved": [{"id": "已有线索id", "note": "如何回收/兑现"}]\n'
        '}\n'
        "若无变化，对应字段为空数组。不要输出额外文字。"
    )

    thread_extract_user: str = (
        "--- 第 {chapter_number} 章正文 ---\n"
        "{chapter_text}\n\n"
        "--- 当前未回收的线索清单 ---\n"
        "{open_threads}\n\n"
        "请分析本章正文中的线索变化并输出 JSON。"
    )

    # ------------------------------------------------------------------
    # Macro editorial review (volume / range level)
    # ------------------------------------------------------------------
    macro_review_system: str = (
        "你是一位资深的小说主编，负责宏观通读审阅。基于给定的多章摘要与正文抽样，"
        "从整体视角找出单章审校发现不了的问题：\n"
        "1. 节奏：是否连续多章同一强度、拖沓或过快，高潮铺垫是否充分；\n"
        "2. 重复：是否有反复出现的桥段、比喻、句式或场景套路；\n"
        "3. 角色声音：不同角色的台词是否趋同、失去辨识度；\n"
        "4. 线索管理：伏笔是否长期悬置、悬念是否被遗忘；\n"
        "5. 结构：各章叙事功能是否失衡（如连续多章无主线推进）。\n"
        "输出一份结构化的审阅报告（Markdown），每个问题给出具体章节位置与改进建议。"
        "只报告问题与建议，不要改写正文。"
    )

    macro_review_user: str = (
        "审阅范围：{scope}\n\n"
        "--- 各章信息（标题/张力/叙事功能/摘要） ---\n"
        "{chapter_digest}\n\n"
        "--- 正文抽样（各章开头与结尾片段） ---\n"
        "{prose_samples}\n\n"
        "请输出宏观审阅报告。"
    )


# A shared default instance — prompts are immutable value objects.
PROMPTS = Prompts()
