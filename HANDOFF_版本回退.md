# RimBook 版本回退功能交接文档

## 一、我们要实现什么

### 核心场景

用户已经生成了第 1 章（含正文 + 设定集 + 实体状态），想**重新生成第 1 章**。

期望行为：点击"重新生成正文"后，系统应当将项目状态**回退到第 1 章生成前**——即设定集为空、实体状态为空、草稿被清除——然后基于干净的状态重新生成正文和 post-write 产物（摘要、设定集扩充、实体状态更新）。

如果有后续章节（如第 2 章已生成），则不能原地回退（会破坏后续章的依赖），应走**分支 fork** 路径：从第 1 章生成前的快照创建新分支，在新分支上重建时间线。

### 两条路径

| 路径 | 触发条件 | 机制 |
|------|---------|------|
| 简单回退 | 有草稿，但后续章无草稿 | `Writer.write()` 内部从预写快照恢复 codex/state，删除新建文件 |
| 分支 fork | 有草稿，且后续章也有草稿 | `fork-for-regen` 端点：构建完整快照 → 创建分支 → 切换 → 清理后续章产物 |

### 设计要点

- codex 是**线性累积的共享状态**，不能简单原地回退（会丢掉后续章的贡献）
- 预写快照（`write-chN-<branch>` label）保存的是生成前的 codex/state 文件
- 回退 = 从预写快照恢复旧文件 + 删除快照中不存在的新文件

---

## 二、这次改了什么

### 已修复的 bug

| 文件 | bug | 修复方式 |
|------|-----|---------|
| `pipeline/writer.py:315` | `_is_state_or_codex` 在 Windows 上用 `"/state/"` 匹配反斜杠路径，永远不匹配，导致回滚逻辑在 Windows 上**完全不执行** | 加 `.replace("\\", "/")` 归一化 |
| `pipeline/writer.py:117` | `_find_last_checkpoint` 用 `f"write-ch{number}"` 前缀（无尾部 `-`），`write-ch1` 会匹配 `write-ch10`、`write-ch100` | 改为 `f"write-ch{number}-"` |
| `versioning/manager.py:420` | `_all_project_files()` 对根目录文件调 `rglob` 返回空，`config.yaml` 等不被快照 | 先检查 `is_file()` 直接添加 |
| `versioning/manager.py:153` | `switch_branch` 用 `restore_checkpoint` 仅覆盖文件，不删除快照中不存在的文件（数据泄漏） | 新增 `_clean_restore` + `_reconstruct_full_state`，遍历父链重建完整状态后做干净恢复 |
| `versioning/manager.py:345` | `restore_checkpoint` 对快照中不存在的文件只是跳过，不删除 | 新增 `delete_missing` 参数，为 True 时删除不在快照中的文件 |
| `pipeline/writer.py:128` | 回滚调用 `restore_checkpoint` 时未启用 `delete_missing`，导致 post-write 新建的 codex 文件残留 | 调用时加 `delete_missing=True` |
| `routes/writer.py:569` | `_clean_codex_post_chapter` 用 `str.replace` 删除片段，会误删其他位置相同文本 | 改为 span-based 区间拼接 |
| `routes/writer.py:509` | `_clean_codex_post_chapter` 不删除新建的空 codex 文件 | 新增：清理后若条目为空则删除整个文件 |
| `routes/writer.py:585` | `_clean_entity_state_post_chapter` 不删除新建的空 entity state 文件 | 同上 |
| `routes/writer.py:83` | `fork_for_regen` 的 `mkdir` 无冲突检测，同一秒两次 fork 会删除第一次的快照 | 循环检测 + 后缀递增 |
| `routes/writer.py:128` | manifest `branch: (fork base)` 是无效分支名，快照不出现在任何分支列表中 | 改为 `branch: {branch_name}` |
| `routes/outline.py:41` | `ChapterOutlineOut` 无 `has_draft` 字段，前端 N+1 查询每章单独请求草稿状态 | 后端添加 `has_draft` 字段 + `_ch_out` 计算草稿是否存在 |
| `WriterStudio.vue` | 无分支名显示、N+1 查询、SSE 错误不重置 writing 状态、Settings 成功消息显示空分支名 | 前端修复 |

### 已验证的内容

- 所有 Python 文件语法检查通过
- `vue-tsc --noEmit` 类型检查通过
- `rimbook` 包从 `src/rimbook/` 加载（`web/backend/routes/` 下有旧副本，未使用）

---

## 三、根因与本轮修复（已完成）

### 根因（journal 铁证）

`测试/.versions/journal.jsonl`：

```json
{"op": "restore", "checkpoint": "20260715-114246-write-ch1-main", "restored": 0, "skipped": 24, "ts": "20260715-114633"}
```

1. **当时运行的是没有 `delete_missing` 的旧代码**：24 个 post-write 新建文件全部 `skipped`，没有 `deleted` 字段。设定集原样保留。
2. **污染快照**：回滚失败后立刻创建了 `20260715-114633-write-ch1-main`（26 个文件，含全部脏 codex/state）。之后若继续用「最新」`write-ch1-*` 回滚，只会把脏状态还原回去，永远清不掉。

### 本轮代码修复

| 改动 | 说明 |
|------|------|
| `writer.py`：`_find_earliest_checkpoint` | 回滚改用**最早**的 `write-chN-` 快照（真正的首次生成前基线），避免被污染的中间快照误导 |
| `writer.py`：ROLLBACK 日志 | `logger.warning` 打印 draft/vm/auto_cp、选用的快照、restored/skipped/deleted |
| `routes/writer.py`：fork-for-regen | 同样改用最早预写快照；构建完整快照时删除不在预写快照中的 state/codex 文件（等价 delete_missing） |

### 已验证

对 `测试` 项目执行 `scripts/verify_rollback.py`：

- earliest = `20260715-114246-write-ch1-main`
- `restore(..., delete_missing=True)` → `deleted=26`
- AFTER: `codex=0 state=0` → **PASS**

当前磁盘上设定集/实体状态已清空；草稿仍在。用户**重启后端**后点「重新生成正文」即可从干净状态重写。

### 仍需注意

- **必须重启 FastAPI**，否则仍跑旧进程。
- 若最早的 `write-chN` 快照被 `prune` 删掉，回滚会失去基线——`max_checkpoints` 勿设太小。
- `_clean_restore` 对「仅含增量文件」的 write-chN HEAD 做分支切换时，父链重建可能不完整（独立问题，简单回退路径不走这里）。

---


## 四、关键文件

| 文件 | 作用 |
|------|------|
| `src/rimbook/pipeline/writer.py` | `write()` 回滚逻辑 + `_find_last_checkpoint` + `_is_state_or_codex` + `_predict_affected_files` |
| `src/rimbook/versioning/manager.py` | `VersionManager`：快照/分支/恢复 + `_clean_restore` + `_reconstruct_full_state` + `restore_checkpoint(delete_missing=)` |
| `src/rimbook/web/backend/routes/writer.py` | `fork-for-regen` 端点 + `_clean_codex_post_chapter` + `_clean_entity_state_post_chapter` |
| `src/rimbook/web/backend/routes/outline.py` | `ChapterOutlineOut` 含 `has_draft` + `_ch_out` |
| `src/rimbook/config.py` | `GenerationConfig`：`auto_checkpoint`、`max_checkpoints` 等配置 |
| `src/rimbook/web/backend/deps.py` | `ProjectDeps`：依赖注入，`version_manager` 的初始化 |
| `web/frontend/src/views/WriterStudio.vue` | 写作界面：按钮逻辑 + 分支显示 + SSE |
| `web/frontend/src/views/Settings.vue` | 版本管理 Tab：分支列表 + 检查点时间线 |

### 存储布局

```
项目根/
  .versions/
    HEAD                    # 当前分支名
    branches.json           # {分支名: HEAD快照名}
    journal.jsonl           # 操作日志
    <时间戳>-<label>/       # 快照目录
      .manifest             # label/timestamp/branch/parent/files
      codex/...             # 快照时的文件副本
      state/...
      drafts/...
```

### 快照 label 约定

- `write-ch{N}-{branch}` — 第 N 章写入前的预写快照（增量，含全部 codex/state）
- `revise-ch{N}-{branch}` — 第 N 章修订前的快照
- `auto-switch-from-{branch}` — 分支切换时自动保存的快照（全量）
- `{branch_name}` — fork-for-regen 创建的完整快照
