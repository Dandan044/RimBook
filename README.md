# RimBook

**LLM 驱动的长篇小说创作工作台。**

用 LLM 写长篇小说，真正的难点不在"写"，而在**长程一致性**：模型会遗忘剧情、混淆世界观设定、让人物 OOC（人物失格）。RimBook 不试图让 LLM "记住"整本书，而是构建一个**创作工作台**——在每次生成时，只把最相关、经过精心组织的上下文精准投喂给模型，并通过"写-检-改"闭环保证一致性。

## 核心机制

| 痛点 | 对应机制 |
|------|---------|
| 内容遗忘 | 章节摘要树 + 滑动窗口 + 分层记忆（全书至今 / 卷回顾）+ 定向检索 |
| 设定混淆 | 结构化设定集（Codex）显式加载 + 一致性校验 |
| 人物 OOC | 人物档案（含语言风格画像）+ 实体当前状态跟踪 + 风格指南注入 |
| 剧情混乱 | 分层大纲（梗概→卷→章节 beat）+ 情节线索账本（伏笔/悬念/承诺） |
| 设定演进 | PostWritePipeline：每章写完后 LLM 自动发现新实体、标记矛盾、抽取线索 |
| Token 超限 | BudgetAllocator：按优先级（beat > chapter > tag > 向量）分配上下文预算 |
| 重写污染 | 预写快照 + 干净回退（`delete_missing`）+ 叙事资产章级清理 / 后续章存在时分支 fork |
| 问题溯源 | LLM Trace：每次调用记录到项目 `.llm_logs/`（按日 JSONL），Web 端可浏览 |

## 设定集（Codex）生命周期

```
作者手动创建 ──→ Planner 引用实体 ──→ 汇编器注入上下文 ──→ Writer 生成
        ↑                                                        │
        │                    阶段性手动修订                        ↓
        │                                          ┌─ 实体状态追踪（谁在哪、知道什么）
        └── PostWritePipeline 自动富化 ←───────────┤
           · 发现新实体 / 更新档案                    └─ 一致性校验收敛
           · 标记矛盾 / 同步关系
```

每个 Codex 条目现在使用**结构化字段**，而非在正文中嵌入 markdown 章节：
- `revelations` — 每章自动发现（章节号、内容、来源引用）
- `contradictions` — 已标记的不一致（章节号、描述、证据、已解决状态）
- `relationships` — 有类型的实体间链接（目标、类型、起始章节、备注）
- `body` — 纯粹的静态档案（外观、性格、背景等）

## 架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Web UI (Vue 3)                                │
│  仪表盘 │ 写作规划 │ 写作 │ 设定集 │ LLM 日志 │ 工作流 │ 设置         │
│                                                                        │
│  · 写作规划：大纲 + 线索账本 / 风格指南 / 故事线 / 宏观审阅          │
│  · 写作工作台：结构化上下文 + 分支/回退重写 + SSE 流式生成           │
│  · 设定集：Tab 式（档案 / 章节发现 / 矛盾）                           │
│  · LLM 日志：按日浏览 `.llm_logs`，查看 prompt / 响应 / token 用量   │
│  · 工作流：流水线可视化（Mermaid）                                    │
├──────────────────────────────────────────────────────────────────────┤
│                      FastAPI Backend (SSE)                             │
├──────────┬──────────┬───────────┬────────────────────────────────────┤
│  Codex   │ Outline  │  Memory   │            Pipeline                 │
│ 设定集   │ 分层大纲  │ 上下文组装 │     写-检-改-富化 流水线          │
│          │          │           │                                    │
│ 实体档案  │ 梗概     │ 摘要树    │ Planner / Writer / Checker         │
│ 世界观    │ 卷大纲   │ 滑动窗口  │ PostWrite（实体/矛盾/线索）       │
│ 发现/矛盾 │ 风格指南 │ 线索账本  │ Versioning（快照/分支/回退/清理） │
│          │ 全书至今 │ 卷回顾    │ Trace（.llm_logs 溯源 + Web 浏览） │
├──────────┴──────────┴───────────┴────────────────────────────────────┤
│             LLM Layer (OpenAI 兼容协议)                                │
│   支持 DeepSeek / OpenAI / 任意兼容端点；可选 reasoning_effort 思考模式 │
├──────────────────────────────────────────────────────────────────────┤
│        存储层：纯文件 (Markdown + YAML)，人类可读可编辑，Git 友好       │
└──────────────────────────────────────────────────────────────────────┘
```

## 配置架构

RimBook 采用**两级配置**，模型配置与项目分离：

```
.rimbook.yaml              ← 全局工作区配置（LLM API / 模型名）
  └── my_novel/
      └── config.yaml      ← 项目配置（标题、作者、生成参数）
```

- **全局配置 `.rimbook.yaml`**：所有项目共享的 LLM 连接信息。创建/删除项目不会影响它。
- **项目配置 `config.yaml`**：每个项目独立的生成参数（temperature、窗口大小等）。
- 合并优先级：**环境变量 > 项目配置 > 全局配置**。

## 安装

```bash
# 克隆项目
git clone https://github.com/Dandan044/RimBook.git
cd RimBook

# 安装 Python 包（开发模式）
pip install -e .

# （可选）安装前端开发依赖
cd web/frontend
npm install
```

## 快速开始

```bash
# 1. 初始化项目
rimbook init my_novel --title "我的小说" --model gpt-4o
cd my_novel

# 2. 配置 API（编辑 config.yaml 或设置环境变量）
export LLM_API_KEY=sk-...

# 3. 添加人物/设定（人物档案请写明"语言风格画像"，用于防 OOC）
rimbook codex add --id lin_yuxuan --name 林雨萱 --type character \
  --aliases "雨萱,阿萱" --tags "主角" --body "..."

# 4. 生成全书梗概
rimbook outline synopsis "一个关于...的故事"

# 5. 规划章节 beat
rimbook outline chapter 1

# 6. 生成章节正文（自动组装上下文→写作→摘要→实体状态→一致性校验）
rimbook write 1

# 7. 查看进度
rimbook status
```

## 工作流（分阶段可介入）

```
init → codex add → outline synopsis → outline chapter → write → check
                                              ↑                           ↓
                                              └──── revise / 修改文件 ←────┘
```

每个阶段都把结果写到**人类可读的 Markdown/YAML 文件**，你可以随时用编辑器修改设定、大纲、摘要，再继续。这是"分阶段可介入"的基础。

## 命令一览

| 命令 | 作用 |
|------|------|
| `init` | 初始化小说项目 |
| `codex add / ls / show / dedup / merge / migrate` | 管理设定集（实体/世界观/地点/势力/物品/时间线） |
| `outline synopsis` | 生成全书梗概 |
| `outline volume` | 规划卷大纲 |
| `outline chapter` | 规划单章 beat |
| `write <n>` | 生成章节正文（完整流水线：上下文组装→写作→校验→富化） |
| `enrich <n>` | 单独运行 PostWrite 富化流水线（从已写章节发现实体、标记矛盾、抽取线索） |
| `check <n>` | 单独跑一致性校验 |
| `revise <n>` | 按要求重写/修订章节 |
| `summary <n>` | 重新生成章节摘要 |
| `style show / generate` | 查看或从已写章节反推写作风格指南 |
| `recap volume / story` | 生成卷情节回顾 / 滚动「全书至今」故事线 |
| `threads ls` | 列出情节线索账本（伏笔/悬念/承诺） |
| `review` | 宏观编辑审阅（节奏/重复桥段/角色声音等，只报告不改稿） |
| `status` | 项目进度总览 |
| `vector rebuild / query` | 向量索引维护与调试（增强检索） |
| `snapshot / rollback` | 版本快照与回滚 |

## 项目结构

### 源码结构

```
src/rimbook/
├── cli.py              # Typer CLI 入口
├── config.py           # 两级配置（全局 .rimbook.yaml + 项目 config.yaml）
├── project.py          # 项目布局与脚手架
├── codex/              # 设定集层：实体档案 CRUD、去重、合并、结构化迁移
│   ├── models.py       # CodexEntry + Revelation / Contradiction / Relationship
│   ├── store.py        # YAML frontmatter 读写
│   ├── sync.py         # 实体状态 ↔ 设定集双向同步
│   ├── resolve.py      # 实体 ID 解析（精确/别名/模糊匹配）、去重、合并
│   └── migrate.py      # 旧格式 → 结构化格式数据迁移
├── llm/                # LLM 抽象层：OpenAI 兼容客户端 + 提示词模板 + Trace
│   └── trace.py        # 每次 LLM 调用的 provenance 日志（.llm_logs/）
├── memory/             # 上下文组装与 Token 预算
│   ├── assembler.py    # 分层上下文组装（SectionInfo 结构化分段）
│   ├── entity_state.py # 实体当前状态（位置/知识/物品/关系）
│   ├── threads.py      # 情节线索账本（伏笔/悬念/承诺）
│   ├── summarizer.py   # 章节摘要 + 卷回顾 + 全书至今
│   ├── window.py       # 前文滑动窗口
│   └── token_budget.py # BudgetAllocator（按优先级分配预算）
├── outline/            # 大纲层：梗概→卷→章节 beat + 风格指南
├── pipeline/           # 写-检-改-富化流水线
│   ├── planner.py      # 章节规划（注入开放线索）
│   ├── writer.py       # 正文生成 + 重写前回退
│   ├── checker.py      # 一致性校验
│   └── post_write.py   # 富化：新实体、矛盾、关系、线索抽取
├── versioning/         # 快照 / 分支 / 干净回退（delete_missing）+ 叙事资产章级清理
├── retrieval/          # 可选向量检索（ChromaDB）
└── web/                # Web 层：FastAPI 后端 + 静态前端
    ├── backend/        # API 路由（含 narrative / llm_logs）、SSE、依赖注入
    └── frontend/       # Vue 3 + TypeScript SPA 源码（源码在仓库根 web/frontend/）
```

### 生成的小说项目结构

```
my_novel/
├── config.yaml              # LLM 配置、生成参数
├── codex/                   # 设定集（结构化档案）
│   ├── characters/          # 人物
│   ├── worldbuilding/       # 世界观
│   ├── locations/           # 地点
│   ├── factions/            # 势力
│   ├── items/               # 物品
│   └── timeline/            # 时间线
├── outline/                 # 分层大纲 + 摘要 + 叙事资产
│   ├── synopsis.md
│   ├── style.md             # 写作风格指南（voice card）
│   ├── story_so_far.md      # 滚动「全书至今」故事线
│   ├── volumes/             # 含卷回顾（recap）
│   └── chapters/
├── drafts/                  # 正文草稿（及可选 chNNN.context.json）
├── final/                   # 定稿
├── state/                   # 运行态：实体状态、线索账本、审阅报告、向量索引
│   ├── threads.yaml         # 情节线索账本
│   └── reviews/             # 宏观审阅报告
├── .llm_logs/               # LLM 调用溯源日志（按日 JSONL，默认 gitignore）
└── .versions/               # 版本快照与分支
```

## 配置

**全局配置**（`.rimbook.yaml`，工作区根目录，所有项目共享）：

```yaml
llm:
  base_url: https://api.openai.com/v1
  api_key: ${LLM_API_KEY}
  model: gpt-4o
  check_model: gpt-4o-mini
  # 思考模式：null/省略 = 关闭（DeepSeek V4 默认会开 thinking，此处显式关闭以保证流式正文）
  # 需要推理时设为 low | medium | high | max
  reasoning_effort: null
  embedding:
    base_url: null
    api_key: ${LLM_API_KEY}
    model: text-embedding-3-small
```

**项目配置**（`my_novel/config.yaml`，每个项目独立）：

```yaml
title: 我的小说
author: 作者
language: zh
generation:
  temperature: 0.85
  max_tokens: 4000
  recent_window_chapters: 1
  summary_history: 6
  auto_consistency_check: true
  auto_fix: false
  max_fix_rounds: 2
  codex_max_tokens: 2000
  codex_entry_max_chars: 1500
  auto_enrich: true    # 写完后自动运行 PostWrite 富化
  auto_checkpoint: true
  max_checkpoints: 50
  story_so_far_every: 5   # 每 N 章刷新「全书至今」（0 = 关闭）
  auto_volume_recap: true # 卷完成后自动生成卷回顾
  track_threads: true     # 写后自动抽取情节线索
  use_vector_retrieval: false  # 是否把向量检索接入默认写作路径
```

环境变量优先级高于配置文件，可覆盖任意字段。

## Web 前端

RimBook 提供基于 **FastAPI + Vue 3 + Element Plus** 的 Web 界面，可视化操作设定集、大纲、写作与校验。

### 启动方式

```bash
# 方式一：CLI 命令（推荐）
rimbook-web

# 方式二：Python 模块
python -m rimbook.web

# 方式三：手动指定端口和工作区
RIMBOOK_WORKSPACE=/path/to/novels RIMBOOK_PORT=8080 rimbook-web
```

浏览器打开 `http://localhost:8000` 即可使用。

### 开发模式（前后端热更新）

```bash
# 终端 1：启动后端
rimbook-web

# 终端 2：启动前端开发服务器
cd web/frontend
npm run dev
# 浏览器打开 http://localhost:5173（自动代理 API 到 8000）
```

### 核心页面

| 页面 | 功能 |
|------|------|
| **仪表盘** | 项目选择/创建/删除、统计卡片、章节进度表、全书梗概 |
| **写作规划** | 大纲树（梗概→卷→章节 beat）+ 线索账本 / 风格指南 / 故事线 / 宏观审阅 |
| **写作工作台** | 三栏布局：结构化上下文 / 正文编辑器 / 校验与富化；支持当前分支显示、重写回退与后续章存在时的分支 fork |
| **设定集** | Tab 式布局（档案 / 章节发现 / 矛盾），按类型管理实体，在线编辑档案，Markdown 渲染 |
| **LLM 日志** | 按日浏览项目 `.llm_logs/`：按任务分组、查看完整 prompt/响应、token 用量统计 |
| **工作流** | 创作流水线可视化（Mermaid 图） |
| **设置** | 全局模型配置（含 `reasoning_effort`）+ 项目生成参数 |

### 重写与版本回退

重新生成某一章时，系统会尽量恢复到该章**首次生成前**的干净状态：

| 路径 | 条件 | 行为 |
|------|------|------|
| 简单回退 | 该章有草稿，后续章无草稿 | 从最早的 `write-chN-` 预写快照恢复，并删除快照中不存在的运行时文件 |
| 分支 fork | 该章有草稿，且后续章也有草稿 | 创建新分支，在干净基线上重写，避免污染主时间线 |

预写快照会纳入：设定集、实体状态、线索账本、故事线、卷大纲（含卷回顾）、审阅报告。  
**不纳入**：风格指南（`outline/style.md`，作者资产，不随章回退）。

文件级恢复之后，还会做**章级内容清理**（兼容旧快照）：剥离该章及之后写入的线索账本条目、覆盖到该章之后的故事线 / 卷回顾，以及快照外的审阅报告。

预写快照由 `auto_checkpoint` 在写作前自动创建；请勿把 `max_checkpoints` 设得过小，以免基线被 prune。

### 启动器说明

`rimbook-web` / `start.bat` 启动前会扫描并清理本机残留的 RimBook Web 进程（不限于 `server.pid`），避免旧进程继续提供过期代码。静态 `index.html` 禁用缓存，前端重建后刷新即可看到新菜单。

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `RIMBOOK_WORKSPACE` | 项目根目录 | 当前工作目录 |
| `RIMBOOK_HOST` | 监听地址 | `0.0.0.0` |
| `RIMBOOK_PORT` | 监听端口 | `8000` |

## 技术栈

- **Python ≥ 3.10** — Typer CLI / Pydantic / FastAPI / ChromaDB
- **Vue 3 + TypeScript** — Pinia / Element Plus / Vite
- **OpenAI 兼容协议** — 支持 DeepSeek、OpenAI 及任意兼容服务
- **纯文件存储** — Markdown + YAML，人类可读可编辑，Git 友好

## 许可证

MIT
