export interface StageMeta {
  id: string
  nameZh: string
  nameEn: string
  description: string
  reads: { source: string; desc: string }[]
  writes: { target: string; desc: string }[]
  llmPrompts: string[]
}

export const STAGES: Record<string, StageMeta> = {
  planner: {
    id: 'planner',
    nameZh: '规划器 (Planner)',
    nameEn: '规划器 (Planner)',
    description: '级联规划：先写全书 Synopsis；规划 Volume 时在同一次对话内产出卷大纲/结局 + 该卷全部章 Beats（章数由模型自决）。禁止无卷生章、禁止重复规划已有卷；仍可对单章补规划或重生成 Beat。',
    reads: [
      { source: '用户输入', desc: '故事 premise / 想法' },
      { source: 'OutlineStore', desc: 'synopsis、已有 volume、已有 chapter outlines（作为上文）' },
      { source: 'CodexStore', desc: '现有实体清单（id / name / aliases / type），注入 prompt 供 LLM 参考' },
    ],
    writes: [
      { target: 'outline/synopsis.md', desc: '全书核心梗概（Markdown）' },
      { target: 'outline/volumes/volN.md', desc: '卷目弧线 + ending + chapters 列表（YAML frontmatter + Markdown body）' },
      { target: 'outline/chapters/chN.md', desc: '章节大纲：beats / entities / tags / notes（YAML + MD）' },
    ],
    llmPrompts: [
      'synopsis_system + synopsis_user',
      'volume_system + volume_user',
      'volume_chapters_system + volume_chapters_user',
      'chapter_outline_system + chapter_outline_user',
    ],
  },
  'context-assembler': {
    id: 'context-assembler',
    nameZh: '上下文组装器',
    nameEn: 'Context Assembler',
    description: '为 Writer 组装 6 层上下文：Codex 实体档案 → Synopsis → Volume 弧线 → 近章摘要 → 滑窗全文 → 实体当前状态。所有数据按 token 预算分配（budget allocator），beat 级引用优先。',
    reads: [
      { source: 'OutlineStore', desc: 'chapter outline（beats / entities / tags）、synopsis、volume arc、近章摘要' },
      { source: 'CodexStore', desc: '实体完整档案（YAML frontmatter + Markdown body），按优先级筛选' },
      { source: 'EntityStateStore', desc: '每个实体的当前状态：位置、状态、知识、物品、关系' },
      { source: 'drafts/ch*.md', desc: '最近 N 章全文（滑动窗口 SlidingWindow）' },
    ],
    writes: [
      { target: 'AssembledContext', desc: '组装后的完整上下文字符串（内存中，传给 Writer）' },
    ],
    llmPrompts: [],
  },
  writer: {
    id: 'writer',
    nameZh: '写作器 (Writer)',
    nameEn: '写作器 (Writer)',
    description: '是整个管线的编排器。接收 AssembledContext → 调用 LLM 生成正文 → 写入 drafts/ → 触发 PostWritePipeline（摘要 + 状态 + 设定集扩充）→ 返回 WriteResult。',
    reads: [
      { source: 'OutlineStore', desc: 'chapter outline（获取 number / beats 等元数据）' },
      { source: 'AssembledContext', desc: '由 ContextAssembler 产出的完整上下文（6 层）' },
    ],
    writes: [
      { target: 'drafts/chN.md', desc: '章节正文（纯 Markdown 散文）' },
      { target: 'PostWritePipeline', desc: '触发后处理管道（摘要 / 状态 / 设定集扩充）' },
    ],
    llmPrompts: ['writer_system + writer_user', 'writer_revise_system + writer_revise_user（修订时）'],
  },
  'post-write': {
    id: 'post-write',
    nameZh: '后处理管道',
    nameEn: 'Post‑Write Pipeline',
    description: 'Writer 生成正文后的自动化后处理，包含四个步骤：摘要撰写 → 实体状态增量 → LLM 设定集扩充 → 落盘。实体 id 经 resolve_entity_id 规范化，防止分叉。',
    reads: [
      { source: 'drafts/chN.md', desc: '刚生成的章节正文（capped 16384 chars）' },
      { source: 'OutlineStore', desc: 'chapter outline（获取 entities / tags）' },
      { source: 'CodexStore', desc: '现有实体档案（判重、合并）' },
      { source: 'EntityStateStore', desc: '现有实体状态（delta apply）' },
    ],
    writes: [
      { target: 'outline/chapters/chN.md', desc: '更新 summary 字段（蒸馏后的梗概）' },
      { target: 'state/entities/*.yaml', desc: '更新实体状态：location / status / knowledge / possessions / relationships' },
      { target: 'codex/**/*.md', desc: '新建实体档案 或 扩充已有档案的 revelations / contradictions / body' },
    ],
    llmPrompts: ['summarize_system + summarize_user', 'entity_delta_system + entity_delta_user', 'codex_enrich_system + codex_enrich_user'],
  },
  checker: {
    id: 'checker',
    nameZh: '一致性校验器',
    nameEn: 'Checker',
    description: '对已生成的章节正文进行 LLM 驱动的一致性审计（八维：人物/设定/剧情/事实/逻辑/数值/常识/因果），可自动修复。发现 blocking issue 则调用 Writer.apply_minimal_fix 定点修复并重新校验（最多 N 轮）。',
    reads: [
      { source: 'drafts/chN.md', desc: '待校验的章节正文' },
    ],
    writes: [
      { target: 'CheckReport', desc: '校验报告：issues 列表、严重程度、证据、建议、修订后的文本' },
      { target: 'drafts/chN.md', desc: '（auto-fix 时）修订后的正文' },
    ],
    llmPrompts: ['checker_system + checker_user', '（auto-fix 时）fix_system + fix_user'],
  },
}

export const NODE_MATCHERS: { pattern: RegExp; id: string }[] = [
  { pattern: /Planner|规划器/i, id: 'planner' },
  { pattern: /Context\s*Assembler|上下文组装/i, id: 'context-assembler' },
  { pattern: /Writer|写作器/i, id: 'writer' },
  { pattern: /Post.?Write|后处理管道/i, id: 'post-write' },
  { pattern: /Checker|校验器/i, id: 'checker' },
]
