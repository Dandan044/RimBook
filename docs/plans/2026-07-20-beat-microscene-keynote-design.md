# Beat 细场景 + 章基调（keynote）设计

日期：2026-07-20

## Goal

将卷规划 v2 的 Step3 从「手法塞进附注」升级为：章级独立 `keynote`（隐性约束）+ beat 下嵌套 `MicroScene`（可执行细场景），并让 Writer 按优先级消费，避免扩写大纲。

## Architecture

```
Step2  RawBeat 链（不变）
  → Step3a 分组 + 每章 keynote + 可选衔接 beat
  → Step3b 按章把每个 beat 拆成 2–5 个 MicroScene
  → 落盘 chNNN.md（keynote + beats[].scenes）
  → Writer：keynote（最高）→ MicroScene → GCO 锚点 → purpose/hook → notes
```

## 数据模型

### MicroScene

| 字段 | 含义 |
|------|------|
| intent | **必填**创作意图（环境/沉默/物件/人物等，不限人物戏） |
| sensory | 环境/感官/氛围方向（可空） |
| action | 人物行为（可空；无人场景留空） |
| dialogue | 对白方向（可空） |
| event | 剧情转折（可空） |
| technique | 写作手法 |
| pacing | 节奏 |
| words | 预计字数（int） |

同一 beat 内细场景应在主导模态上有变化；禁止为填字段虚构人物/对白。

### SceneBeat（扩展）

保留 `goal/conflict/outcome/entities`，新增 `scenes: list[MicroScene]`。

### ChapterOutline（扩展）

新增 `keynote: list[str]`——本章特有隐性约束（建议 2–5 条，够用即止，勿套公式前缀）。`notes` 仅作作者备忘。

### ChapterAssignment / VolumeBeatData

`chapter_map` 项增加 `keynote`。细化结果以 chapter 落盘为准，不在 beats.yaml 双份存 MicroScene（避免双真相）。

## Step3 管线

**3a 分组+基调（整卷一次）**  
输入 raw beats + 卷信息 → chapters 切分、bridge beats、title/purpose/tension/hook/**keynote**。

**3b 按章细化（每章一次）**  
输入该章 beats + keynote → 每 beat 产出 2–5 MicroScene；必须服从 keynote。

重跑：改 raw beat → 全量 3a+3b；改单章 keynote/scenes → 可只重跑该章 3b。

## Writer 注入

1. keynote 块（标注：必须渗透，禁止明说）
2. MicroScene 序列：以 intent 为首，其后只列非空的 sensory/action/dialogue/event
3. beat GCO 一行摘要
4. purpose / hook / value_shift
5. notes（降权）

空模态字段表示该模态不存在——Writer 勿补写人物戏。无 scenes/keynote 时回退旧路径。

## 前端

- 章编辑器：章基调多行清单（hint：2–5 条、勿套公式前缀）；细场景以创作意图为首，感官/动作/对白按需
- 卷面板：beat 链 + 重新组装不变；进度条/遮罩使用主题 token
- notes UI 降权

## 兼容

- 缺字段 → 空列表 / 旧 GCO 路径
- 旧 MicroScene 无 `intent` 时，读取时用 `event` 或 `action` 回填
- 旧「手法在 notes」不自动迁移；重新组装即覆盖

## 实现顺序

1. models + store + API 类型
2. prompts + planner Step3a/3b
3. assembler 注入
4. 前端 OutlineEditor
5. 单测 + 卷1 reassemble 验收
