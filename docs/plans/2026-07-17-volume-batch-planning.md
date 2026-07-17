# 卷批量规划（Volume → 全章 Beat）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将「规划一卷」升级为原子操作：同会话产出卷大纲（含 `ending`）+ 本卷全部章 beat，并维护 `chapters`；禁止无卷生章、禁止重复 LLM 规划同一卷；保留单章 beat 生成/重规划（可往已有卷追加）。

**Architecture:** Planner 采用同会话两轮 LLM（先结构化卷，再批量章 JSON）；`OutlineStore` 提供 `sync_volume_chapters` 以章侧 `volume` 回写卷的 `chapters`；API/CLI/前端统一硬约束（409 重复卷、400 无卷）。单章路径仍走现有 `plan_chapter_detailed`，但强制已存在卷，并在写章后同步 `chapters`。

**Tech Stack:** Python 3.10+ / Pydantic / FastAPI / Typer / Vue3+Element Plus；新增 pytest（dev）做无真实 LLM 的单元测试。

**已确认产品规则：**

1. 生成卷时，必须在一次对话内同时生成该卷全部章 beat（章数由 LLM 自决）。
2. 禁止在没有卷的情况下生成章。
3. 禁止对已存在的卷再次 LLM 规划（不可重复生成同一卷）。
4. 卷规划完成后，允许用单章 beat 往该卷追加新章，或重规划已有章 beat。
5. 修复 `chapters` / `ending` 未维护问题。

---

## 背景与现状（实现者必读）

当前分层：`synopsis → volume.arc(纯文本) → chapter beats(JSON)`。

痛点：

- `Planner.plan_volume`（`src/rimbook/pipeline/planner.py`）只写 `arc`，从不填 `ending` / `chapters`。
- 章归属权威在 `ChapterOutline.volume`，卷上 `chapters` 半废弃；`clean_volume_recaps_post_chapter` 依赖空的 `chapters` 会误清 recap。
- 前端「新卷」只规划 arc；「新章节」在无卷时也会创建「未分卷章节」。

目标形态：

```
plan_volume(N) [N 不存在]
  turn1: JSON { title, arc, ending, chapter_count? }
  turn2: JSON { chapters: [ { title, beats, purpose, ... }, ... ] }
  persist: vol(ending, chapters=[...]) + 各章文件(volume=N)

plan_chapter / regenerate [必须 volume 已存在]
  单章 JSON（现有逻辑）
  persist 后 sync_volume_chapters(volume)
```

---

### Task 1: 测试脚手架 + 归属同步 helper

**Files:**
- Create: `pyproject.toml`（追加 optional-dev / pytest 配置）
- Create: `tests/conftest.py`
- Create: `tests/outline/test_sync_volume_chapters.py`
- Modify: `src/rimbook/outline/store.py`
- Modify: `src/rimbook/outline/__init__.py`（如需导出）

**Step 1: 在 pyproject.toml 增加 pytest**

在 `[project]` 后追加：

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

**Step 2: 写失败测试 — `sync_volume_chapters`**

```python
# tests/outline/test_sync_volume_chapters.py
from pathlib import Path
from rimbook.outline.models import ChapterOutline, VolumeOutline
from rimbook.outline.store import OutlineStore
from rimbook.project import ProjectPaths  # 若实际类名不同，按 codebase 调整

def _store(tmp_path: Path) -> OutlineStore:
    # 使用项目既有的临时 project 构造方式；若无工厂，手动 mkdir outline/volumes|chapters
    ...

def test_sync_volume_chapters_from_chapter_pointers(tmp_path):
    store = _store(tmp_path)
    store.write_volume(VolumeOutline(number=1, title="A", arc="arc", chapters=[], ending="end"))
    store.write_chapter(ChapterOutline(number=3, title="c3", volume=1, beats=[]))
    store.write_chapter(ChapterOutline(number=1, title="c1", volume=1, beats=[]))
    store.write_chapter(ChapterOutline(number=2, title="c2", volume=2, beats=[]))

    nums = store.sync_volume_chapters(1)
    assert nums == [1, 3]
    vol = store.read_volume(1)
    assert vol is not None
    assert vol.chapters == [1, 3]
```

**Step 3: 实现 `OutlineStore.sync_volume_chapters`**

```python
def sync_volume_chapters(self, volume_number: int) -> list[int]:
    """Recompute VolumeOutline.chapters from ChapterOutline.volume pointers."""
    vol = self.read_volume(volume_number)
    if vol is None:
        raise FileNotFoundError(f"Volume {volume_number} not found")
    nums = sorted(
        c.number for c in self.list_chapters() if c.volume == volume_number
    )
    if list(vol.chapters or []) != nums:
        vol.chapters = nums
        self.write_volume(vol)
    return nums
```

在 `write_chapter` 末尾可选调用同步（见 Task 4；本 Task 先只提供显式方法，避免循环依赖）。

**Step 4: 安装并跑通测试**

```bash
pip install -e ".[dev]"
pytest tests/outline/test_sync_volume_chapters.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml tests/ src/rimbook/outline/store.py
git commit -m "feat(outline): sync volume.chapters from chapter volume pointers"
```

---

### Task 2: Prompt 与解析 — 卷两轮 JSON 协议

**Files:**
- Modify: `src/rimbook/llm/prompts.py`
- Modify: `src/rimbook/llm/prompts_store.py`
- Create: `tests/pipeline/test_parse_volume_batch.py`
- Modify: `src/rimbook/pipeline/planner.py`（先加解析 helper，暂不改 `plan_volume` 主流程）

**Step 1: 定义 JSON 形状（写入计划注释与 prompt）**

**Turn 1 — 卷结构（`generate_json`）：**

```json
{
  "title": "卷标题",
  "arc": "本卷弧线 400-600 字级叙述（可略短于旧纯文本要求，因结构字段分流）",
  "ending": "本卷收束与衔接下卷的钩子（必填，非空）",
  "chapter_count": 6
}
```

约束：`chapter_count` 建议 4–12（prompt 软约束；解析时 clamp 到 `[3, 20]`，越界仍接受但记 warning）。

**Turn 2 — 全章（`generate_json`，同会话）：**

```json
{
  "chapters": [
    {
      "title": "...",
      "entities": ["id", ...],
      "tags": ["..."],
      "notes": "...",
      "purpose": "...",
      "value_shift": "...",
      "tension": 3,
      "hook": "...",
      "story_date": "...",
      "elapsed": "...",
      "beats": [
        {"goal": "...", "conflict": "...", "outcome": "...", "entities": ["id", ...]}
      ]
    }
  ]
}
```

要求：`chapters.length` 必须等于 turn1 的 `chapter_count`（不等则 ValueError，由上层决定是否重试一轮；首版：**抛错不落盘**）。

**Step 2: 更新 `Prompts`**

- 将 `volume_system` / `volume_user` 改为要求 **仅输出 Turn1 JSON**（不再纯 Markdown）。
- 新增：
  - `volume_chapters_system`
  - `volume_chapters_user`（占位：`chapter_count`, `volume_title`, `volume_arc`, `volume_ending`, `start_chapter_number`, 实体/线索块可复用）

`volume_chapters_user` 示例要点：

- 必须输出恰好 `{chapter_count}` 章；
- 章与章因果衔接、张力起伏、服务本卷 `ending`；
- 实体 id 规则与单章 prompt 相同；
- 章号由调用方分配（模型不输出 number，或忽略其 number）。

**Step 3: 在 `prompts_store.py` 注册新 key 的元数据**（`STAGE_PLANNING`，占位符说明与旧 volume_* 同级）。

**Step 4: 解析 helper + 测试**

在 `planner.py` 增加：

```python
@dataclass
class VolumePlanResult:
    volume: VolumeOutline
    chapters: list[ChapterOutline]
    warnings: list[str] = field(default_factory=list)

def _parse_volume_json(data: dict, *, number: int, title_hint: str) -> tuple[str, str, str, int, list[str]]:
    """Return (title, arc, ending, chapter_count, warnings)."""
    ...

def _parse_volume_chapters_json(
    data: dict,
    *,
    volume: int,
    start_number: int,
    expected_count: int,
    codex: CodexStore | None,
) -> tuple[list[ChapterOutline], list[str]]:
    """Parse chapters array; assign numbers start_number..; reuse _parse_chapter_json per item."""
    ...
```

单测用固定 dict，不调 LLM。

**Step 5: Commit**

```bash
git commit -m "feat(planner): add volume+chapters JSON prompt protocol and parsers"
```

---

### Task 3: 重写 `Planner.plan_volume`（同会话两轮 + 硬约束）

**Files:**
- Modify: `src/rimbook/pipeline/planner.py`
- Create: `tests/pipeline/test_plan_volume_batch.py`

**Step 1: 写失败测试（Fake LLM）**

用可注入的假 `LLMClient`：记录 `messages` 历史；第一次 `generate_json` 返回卷 JSON，第二次返回 chapters JSON。断言：

- 第二次调用的 messages 含第一轮 assistant 内容（同会话）；
- persist 后 `read_volume(1).ending` 非空、`chapters == [1,2,...]`；
- 各章 `volume == 1` 且有 beats；
- 对已存在卷再调用 → 抛自定义异常或 `FileExistsError` / `ValueError`。

**Step 2: 实现 `plan_volume`**

伪代码：

```python
def plan_volume(self, number: int, *, title: str = "", persist: bool = True) -> VolumePlanResult:
    if self.outline.read_volume(number) is not None:
        raise FileExistsError(f"第 {number} 卷已存在，禁止重复规划")

    synopsis = ...
    # 与旧逻辑相同的上下文块：existing volumes, prev chapters, entities, threads
    messages = self.llm.as_chat(system=self.prompts.volume_system, user=...)
    with self.trace.begin("volume", ...) as t:
        vol_data = self.llm.generate_json(messages, temperature=0.7)
        t.record(...)  # 如 trace 只支持 generate，则记录 content=json.dumps

    title, arc, ending, chapter_count, warnings = _parse_volume_json(vol_data, number=number, title_hint=title)
    if not ending.strip():
        raise ValueError("卷规划缺少 ending")

    # 追加同会话：assistant(turn1) + user(turn2)
    messages = list(messages)
    messages.append({"role": "assistant", "content": json.dumps(vol_data, ensure_ascii=False)})
    messages.append({"role": "user", "content": self.prompts.volume_chapters_user.format(
        chapter_count=chapter_count,
        volume_title=title,
        volume_arc=arc,
        volume_ending=ending,
        start_chapter_number=self.outline.last_chapter_number() + 1,
        entity_registry_block=...,
        open_threads_block=...,
    )})
    # system 已在 messages[0]；若需换 system，首版保持 volume_system，依赖 user+volume_chapters_system
    # 更干净做法：messages[0] = volume_chapters_system，或 as_chat 重建并带 history
    # 【采用】重建：
    history = [
        {"role": "user", "content": <turn1 user>},
        {"role": "assistant", "content": json.dumps(vol_data, ensure_ascii=False)},
    ]
    messages2 = self.llm.as_chat(
        system=self.prompts.volume_chapters_system,
        user=self.prompts.volume_chapters_user.format(...),
        history=history,
    )

    with self.trace.begin("volume_chapters", ..., volume=number) as t:
        ch_data = self.llm.generate_json(messages2, temperature=0.7)
        t.record(...)

    start = self.outline.last_chapter_number() + 1
    chapters, w2 = _parse_volume_chapters_json(
        ch_data, volume=number, start_number=start,
        expected_count=chapter_count, codex=self.codex,
    )
    warnings.extend(w2)

    vol = VolumeOutline(
        number=number, title=title, arc=arc, ending=ending,
        chapters=[c.number for c in chapters], recap="",
    )
    if persist:
        self.outline.write_volume(vol)
        for ch in chapters:
            self.outline.write_chapter(ch)
        self.outline.sync_volume_chapters(number)
    return VolumePlanResult(volume=vol, chapters=chapters, warnings=warnings)
```

**兼容性：** 旧调用方若期望 `VolumeOutline`，更新为 `.volume`；见 Task 5/6。

**Step 3: 强化 `plan_chapter_detailed`**

在方法开头：

```python
if volume is None:
    raise ValueError("必须指定所属卷：禁止在没有卷的情况下规划章节")
vol = self.outline.read_volume(volume)
if vol is None:
    raise FileNotFoundError(f"第 {volume} 卷不存在，请先规划卷")
```

persist 成功后：

```python
self.outline.sync_volume_chapters(volume)
```

重规划时：若请求未带 volume，则使用已有章的 `volume`；若仍为空 → 同上报错。

**Step 4: 跑测试**

```bash
pytest tests/pipeline/ -v
```

**Step 5: Commit**

```bash
git commit -m "feat(planner): batch-plan volume with all chapter beats in one conversation"
```

---

### Task 4: 写章路径始终同步 `chapters`；修 recap cleanup

**Files:**
- Modify: `src/rimbook/outline/store.py` — `write_chapter` / `update` 路径
- Modify: `src/rimbook/versioning/cleanup.py`
- Create: `tests/versioning/test_clean_volume_recaps.py`
- Modify: `src/rimbook/web/backend/routes/outline.py` — `update_chapter` / `update_volume`

**Step 1: `write_chapter` 后同步**

```python
def write_chapter(self, ch: ChapterOutline) -> Path:
    ...
    atomic_write(...)
    if ch.volume is not None and self.read_volume(ch.volume) is not None:
        try:
            self.sync_volume_chapters(ch.volume)
        except FileNotFoundError:
            pass
    return path
```

注意：若章从卷 A 改到卷 B，需同步两侧。在 `update_chapter` API 层：

```python
old = deps.outline.read_chapter(number)
...
deps.outline.write_chapter(ch)
if old and old.volume and old.volume != ch.volume:
    deps.outline.sync_volume_chapters(old.volume)
# write_chapter 已 sync 新 volume
```

**Step 2: 修 `clean_volume_recaps_post_chapter`**

改为优先用章指针：

```python
def clean_volume_recaps_post_chapter(outline: OutlineStore, number: int) -> int:
    cleared = 0
    # 先按章文件归属判断
    chapters = outline.list_chapters()
    by_vol: dict[int, list[int]] = {}
    for c in chapters:
        if c.volume is not None:
            by_vol.setdefault(c.volume, []).append(c.number)

    for vol in outline.list_volumes():
        if not (vol.recap or "").strip():
            continue
        chs = by_vol.get(vol.number) or list(vol.chapters or [])
        # 仅当能确定归属时：有章 >= number 才清；完全无章且 chapters 空 → 不清（或保守清）
        if not chs:
            continue  # 改变旧行为：未知成员不再误清
        if any(c >= number for c in chs):
            vol.recap = ""
            outline.write_volume(vol)
            cleared += 1
    ...
```

单测覆盖：空 `vol.chapters` 但章文件 `volume=1` 含 ch5 → 回滚到 5 应清 recap；无关卷不清。

**Step 3: `update_volume` 手改时**

- 允许手改 `arc` / `ending` / `title`；
- **忽略客户端传入的 `chapters`**，始终 `sync_volume_chapters(number)` 后返回，避免 UI 写脏。

**Step 4: Commit**

```bash
git commit -m "fix(outline): keep volume.chapters in sync; fix recap cleanup membership"
```

---

### Task 5: Web API（src 下现行后端）

**Files:**
- Modify: `src/rimbook/web/backend/routes/outline.py`
- 检查：`web/backend/routes/outline.py`（旧副本）——若仍被引用则同步；否则在 README/注释标明废弃，**本任务以 `src/rimbook/web/backend` 为准**。

**Step 1: 响应模型**

```python
class VolumePlanOut(BaseModel):
    volume: VolumeOutlineOut
    chapters: list[ChapterOutlineOut]
    warnings: list[str] = []
```

**Step 2: `POST /volumes`**

```python
@router.post("/volumes", response_model=VolumePlanOut)
def plan_volume(...):
    existing = deps.outline.list_volumes()
    number = max((v.number for v in existing), default=0) + 1
    if deps.outline.read_volume(number) is not None:  # 防御
        raise HTTPException(409, detail=f"第 {number} 卷已存在")
    task_registry.register(..., "plan_volume", number, "正在规划卷及全部章节…")
    try:
        result = deps.planner.plan_volume(number, title=req.title)
        return VolumePlanOut(
            volume=_vol_out(result.volume),
            chapters=[_ch_out(c, deps.paths) for c in result.chapters],
            warnings=result.warnings,
        )
    except FileExistsError as e:
        raise HTTPException(409, detail=str(e))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    finally:
        task_registry.unregister(...)
```

**Step 3: `POST /chapters` 与 regenerate**

```python
if req.volume is None:
    raise HTTPException(400, detail="必须指定所属卷，请先规划卷")
if deps.outline.read_volume(req.volume) is None:
    raise HTTPException(400, detail=f"第 {req.volume} 卷不存在")
```

捕获 planner 的 `ValueError` / `FileNotFoundError` → 400。

**Step 4: Commit**

```bash
git commit -m "feat(api): volume plan returns chapters; require volume for chapter plan"
```

---

### Task 6: CLI

**Files:**
- Modify: `src/rimbook/cli.py`（`outline volume` / `outline chapter`）

**Step 1: `outline volume`**

- 调用新 `plan_volume`；
- 若卷已存在：`typer.Exit(code=1)` 并打印错误；
- 成功后打印 arc、ending、章列表摘要（章号+标题+beat 数）。

**Step 2: `outline chapter`**

- `--volume` 改为 **必填**（去掉 Optional，或校验 None）；
- 卷不存在则退出非零。

**Step 3: 手动烟测（无 LLM 可跳过，依赖单元测试）**

**Step 4: Commit**

```bash
git commit -m "feat(cli): volume plans all chapters; chapter requires --volume"
```

---

### Task 7: 前端 OutlineEditor

**Files:**
- Modify: `web/frontend/src/api/index.ts`
- Modify: `web/frontend/src/views/OutlineEditor.vue`
- Modify: `web/frontend/src/views/pipelineData.ts`（文档化文案，如有卷规划描述）

**Step 1: API 类型**

```ts
export interface VolumePlanResult {
  volume: VolumeOutline
  chapters: ChapterOutline[]
  warnings?: string[]
}

export const planVolume = (projectId: string, title?: string) =>
  http.post<VolumePlanResult>(`/projects/${projectId}/outline/volumes`, { title: title || '' })
    .then(r => r.data)

export const planChapter = (
  projectId: string,
  data: { volume: number; title?: string; hint?: string },
) => ...
```

**Step 2: `addVolume` / `confirmAddVolume`**

- 确认文案改为：将规划第 N 卷大纲、结局，并一次性生成卷内全部章节 beat。
- 成功后：`volumes.push(result.volume)`，`chapters` 合并 `result.chapters`，`fetchData()` 刷新树。
- 处理 409：提示「该卷已存在，不能重复规划」。

**Step 3: `confirmAddChapter` / `addChapter`**

- 无卷时：**禁用按钮**或点击直接 `ElMessage.warning('请先规划卷')`，禁止请求。
- 有卷时：归属「最后一卷」（或当前选中卷，若 UI 有选中态则优先选中卷；首版保持 last volume）。
- 成功后刷新对应卷的 `chapters` 列表（依赖后端 sync，再 `fetchData`）。

**Step 4: `generateBeat`（单章重规划）**

- 若 `editingChapter.volume` 为空：提示先在表单选择卷并保存，或拒绝生成。
- 请求必须带 `volume: number`。

**Step 5: 卷编辑表单**

- `ending` 字段确保展示/可编辑（已有则核对绑定）；
- `chapters` 只读展示（由系统维护），勿当作可随意编辑的主输入。

**Step 6: Commit**

```bash
git commit -m "feat(web): volume plan creates all chapter beats; block chapter-without-volume"
```

---

### Task 8: 文档与回归清单

**Files:**
- Modify: `README.md`（大纲/CLI 相关段落）
- Modify: `web/frontend/src/views/pipelineData.ts`

**Step 1: README 更新要点**

- 规划顺序：梗概 → **卷（含全章 beat）** → （可选）单章补规划/重规划。
- CLI：`rimbook outline volume N` 会生成该卷全部章；`outline chapter` 必须 `--volume`。
- 说明：已存在卷不可再次 `plan_volume`；手改 arc/ending 仍可用编辑器。

**Step 2: 手工回归清单（实施后勾选）**

- [ ] 新项目：梗概 → 生成卷 → 树中出现多章且均挂在该卷
- [ ] 卷文件 frontmatter 含非空 `ending` 与 `chapters`
- [ ] 再次点「规划新卷」得到下一卷号成功；对已存在号 CLI 指定重复失败
- [ ] 无卷时前端无法生成章；API 返回 400
- [ ] 有卷时「新章节」追加一章，`vol.chapters` 增长
- [ ] 单章「重新生成 beat」成功且保留 summary
- [ ] 写两章后回退章节，仅相关卷 recap 被清理

**Step 3: Commit**

```bash
git commit -m "docs: document volume batch planning constraints"
```

---

## 非目标（YAGNI）

- 不做「整书一次拆多卷」。
- 不做卷的可视化张力图 UI。
- 不删除单章规划入口。
- 不强制迁移历史「未分卷章节」（只读兼容；新规划禁止再产生）。
- 首版不对 turn2 章数不匹配做自动重试（失败则整次不落盘，用户可重试生成**下一新卷号**前需确保未部分写入——见下方原子性）。

## 原子性约定

- **先完整解析两轮成功，再写盘**（先内存得到 `vol + chapters`，再 `write_volume` + 循环 `write_chapter`）。
- 若第二轮失败：不写卷、不写章。
- 若写盘中途失败：尽力 `sync`；可接受残留时由用户手工清理（首版不引入事务层）。可选增强：写盘前若 `persist`，先写卷再写章；失败时删除本批新建章文件——**作为 Task 3 的可选 polish**，有余力再做。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 长卷 JSON 截断 | clamp 章数≤20；temperature 0.7；失败明确报错 |
| 旧前端仍当 `planVolume` 返回 VolumeOutline | 同步改 `api/index.ts` + Vue |
| 旧 `web/backend` 漂移 | 只改 `src/rimbook/web/backend`；确认启动入口 |
| 历史未分卷章 | 树仍显示「未分卷」；新操作不能再创建 |

## 建议实现顺序

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

每完成一个 Task 提交一次，便于回滚。

---

## 批准栏

- [ ] 产品规则确认无误
- [ ] 计划可执行，批准开工

**批准后执行方式（二选一）：**

1. **本会话 Subagent 驱动** — 按 Task 派生子代理，任务间复查  
2. **新会话执行** — 使用 executing-plans，按本文件逐步落地  

批准时请回复：`批准` + 选项 `1` 或 `2`。
)
