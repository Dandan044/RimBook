# RimBook

**LLM 驱动的长篇小说创作工作台。**

用 LLM 写长篇小说，真正的难点不在"写"，而在**长程一致性**：模型会遗忘剧情、混淆世界观设定、让人物 OOC（人物失格）。RimBook 不试图让 LLM "记住"整本书，而是构建一个**创作工作台**——在每次生成时，只把最相关、经过精心组织的上下文精准投喂给模型，并通过"写-检-改"闭环保证一致性。

## 核心机制

| 痛点 | 对应机制 |
|------|---------|
| 内容遗忘 | 章节摘要树 + 滑动窗口 + 定向检索 |
| 设定混淆 | 结构化设定集（Codex）显式加载 + 一致性校验 |
| 人物 OOC | 人物档案（含语言风格画像）+ 实体当前状态跟踪 |
| 剧情混乱 | 分层大纲（梗概→卷→章节 beat）+ 大纲遵循检查 |

## 架构

```
┌─────────────────────────────────────────────────────┐
│                    Web UI (Vue 3)                    │
│   仪表盘 │ 设定集 │ 大纲编辑器 │ 写作工作台 │ 设置    │
├─────────────────────────────────────────────────────┤
│                 FastAPI Backend (SSE)                │
├──────────┬──────────┬───────────┬───────────────────┤
│  Codex   │ Outline  │  Memory   │     Pipeline      │
│ 设定集   │ 分层大纲  │ 上下文组装 │  写-检-改 流水线  │
│          │          │           │                   │
│ 人物档案  │ 梗概     │ 摘要树    │ Planner (规划)    │
│ 世界观    │ 卷大纲   │ 滑动窗口  │ Writer  (写作)    │
│ 地点/势力 │ 章节beat │ 实体状态  │ Checker (校验)    │
│ 物品/时间 │          │ Token预算 │                   │
│          │          │ 向量检索  │                   │
├──────────┴──────────┴───────────┴───────────────────┤
│          LLM Layer (OpenAI 兼容协议)                 │
│     支持 DeepSeek / OpenAI / 任意兼容端点             │
├─────────────────────────────────────────────────────┤
│     存储层：纯文件 (Markdown + YAML)，人类可读可编辑    │
└─────────────────────────────────────────────────────┘
```

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
| `codex add / ls / show / dedup / merge` | 管理设定集（人物/世界观/地点/势力/物品/时间线） |
| `outline synopsis` | 生成全书梗概 |
| `outline volume` | 规划卷大纲 |
| `outline chapter` | 规划单章 beat |
| `write <n>` | 生成章节正文（完整流水线） |
| `check <n>` | 单独跑一致性校验 |
| `revise <n>` | 按要求重写/修订章节 |
| `summary <n>` | 重新生成章节摘要 |
| `status` | 项目进度总览 |
| `vector rebuild / query` | 向量索引维护与调试（增强检索） |
| `snapshot / rollback` | 版本快照与回滚 |

## 项目结构

### 源码结构

```
src/rimbook/
├── cli.py              # Typer CLI 入口
├── config.py           # 两级配置（全局 + 项目）
├── project.py          # 项目布局与脚手架
├── codex/              # 设定集层：实体档案 CRUD、去重、合并
├── llm/                # LLM 抽象层：OpenAI 兼容客户端 + 提示词模板
├── memory/             # 上下文组装：摘要树、滑动窗口、实体状态、Token 预算
├── outline/            # 大纲层：梗概→卷→章节 beat
├── pipeline/           # 写-检-改流水线：Planner / Writer / Checker
├── retrieval/          # 可选向量检索（ChromaDB）
└── web/                # Web 层：FastAPI 后端 + 静态前端
    ├── backend/        # API 路由、SSE 流式、依赖注入
    └── frontend/       # Vue 3 + TypeScript SPA 源码
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
├── outline/                 # 分层大纲 + 摘要
│   ├── synopsis.md
│   ├── volumes/
│   └── chapters/
├── drafts/                  # 正文草稿
├── final/                   # 定稿
├── state/                   # 运行态：实体状态、向量索引
└── .versions/               # 版本快照
```

## 配置

`config.yaml` 示例：

```yaml
title: 我的小说
language: zh
llm:
  base_url: https://api.openai.com/v1   # 任意 OpenAI 兼容端点
  api_key: ${LLM_API_KEY}                # 环境变量引用，避免硬编码
  model: gpt-4o
  check_model: gpt-4o-mini               # 校验用更便宜的模型
  embedding:
    model: text-embedding-3-small
generation:
  temperature: 0.85
  recent_window_chapters: 1              # 滑动窗口原文章数
  summary_history: 6                     # 携带的章节摘要数
  auto_consistency_check: true
  auto_fix: false                        # 是否自动修复
  max_fix_rounds: 2
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
| **仪表盘** | 项目选择/创建、统计卡片、章节进度表、全书梗概 |
| **设定集** | 按 6 种类型管理人物/世界观/地点/势力/物品/时间线，在线编辑档案 |
| **大纲** | 树状浏览梗概→卷→章节，LLM 生成或手动编辑 beat |
| **写作工作台** | 三栏布局：左栏上下文预览 / 中栏正文编辑器 / 右栏校验报告，SSE 流式生成 |
| **设置** | LLM / Embedding / 生成参数配置 |

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
