"""RimBook command-line interface.

Commands are organized by *stage* so the workflow is a natural progression:
``init`` → ``codex add`` → ``outline synopsis`` → ``outline chapter`` →
``write chapter`` → ``check``. Every stage writes a checkpoint to disk that
a human can review or hand-edit before continuing.

A single :func:`deps` factory wires up all the components from a project
directory, so each command stays short and focused.
"""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .codex import CodexEntry, CodexStore
from .config import load_config
from .llm import LLMClient, Prompts, load_prompts
from .llm.trace import TraceStore
from .memory import (
    ContextAssembler,
    EntityStateStore,
    SlidingWindow,
    Summarizer,
    ThreadStore,
)
from .outline import OutlineStore
from .pipeline import Checker, Planner, Writer
from .project import ProjectPaths, locate_project, scaffold_project

app = typer.Typer(
    name="rimbook",
    help="LLM-powered long-form fiction writing workbench.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

# Shared, immutable prompt bundle.
# Overridden per project via the workspace-level prompts.yaml (see Deps.prompts).
PROMPTS = Prompts()


# ======================================================================
# Dependency wiring
# ======================================================================
class Deps:
    """Lazily-assembled bundle of all components for one project."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.config = load_config(project_dir)
        self.paths = ProjectPaths(root=project_dir)
        self._llm: LLMClient | None = None
        self._prompts: Prompts | None = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.config.llm)
        return self._llm

    @property
    def prompts(self) -> Prompts:
        # Workspace-level overrides from <workspace>/prompts.yaml.
        if self._prompts is None:
            try:
                ws = self.project_dir.parent.resolve()
            except Exception:
                ws = self.project_dir.parent
            self._prompts = load_prompts(ws)
        return self._prompts

    @property
    def codex(self) -> CodexStore:
        return CodexStore(self.paths)

    @property
    def outline(self) -> OutlineStore:
        return OutlineStore(self.paths)

    @property
    def entity_state(self) -> EntityStateStore:
        return EntityStateStore(self.paths)

    @property
    def window(self) -> SlidingWindow:
        return SlidingWindow(self.paths)

    @property
    def threads(self) -> ThreadStore:
        return ThreadStore(self.paths)

    @property
    def retriever(self):
        """Optional vector retriever, wired in when ``use_vector_retrieval`` is on."""
        if not self.config.generation.use_vector_retrieval:
            return None
        try:
            from .retrieval import VectorRetriever

            return VectorRetriever(self.paths, self.llm)
        except Exception:
            return None

    @property
    def assembler(self) -> ContextAssembler:
        return ContextAssembler(
            self.paths,
            codex=self.codex,
            outline=self.outline,
            entity_state=self.entity_state,
            window=self.window,
            generation=self.config.generation,
            retriever=self.retriever,
            threads=self.threads,
        )

    @property
    def trace(self) -> TraceStore:
        return TraceStore(self.project_dir)

    @property
    def summarizer(self) -> Summarizer:
        return Summarizer(
            self.llm, self.prompts, self.outline,
            trace=self.trace, project_name=self.project_dir.name,
        )

    @property
    def writer(self) -> Writer:
        return Writer(
            self.paths,
            llm=self.llm,
            prompts=self.prompts,
            outline=self.outline,
            assembler=self.assembler,
            summarizer=self.summarizer,
            entity_state=self.entity_state,
            codex=self.codex,
            generation=self.config.generation,
            trace=self.trace,
            project_name=self.project_dir.name,
        )

    @property
    def planner(self) -> Planner:
        return Planner(
            self.llm, self.prompts, self.outline,
            codex=self.codex, threads=self.threads, trace=self.trace,
            project_name=self.project_dir.name,
        )

    @property
    def checker(self) -> Checker:
        return Checker(
            self.paths,
            llm=self.llm,
            prompts=self.prompts,
            assembler=self.assembler,
            outline=self.outline,
            trace=self.trace,
            project_name=self.project_dir.name,
        )


def _resolve_project(project: Optional[Path]) -> Path:
    if project is not None:
        return project.resolve()
    try:
        return locate_project()
    except FileNotFoundError as exc:
        console.print(f"[red]错误：[/red]{exc}")
        raise typer.Exit(code=1)


def _load_deps(project: Optional[Path]) -> Deps:
    return Deps(_resolve_project(project))


# ======================================================================
# init / config
# ======================================================================
@app.command()
def init(
    name: str = typer.Argument(..., help="项目目录名"),
    title: str = typer.Option("Untitled Novel", "--title", "-t", help="小说标题"),
    author: str = typer.Option("", "--author", "-a", help="作者"),
    base_url: str = typer.Option(
        "https://api.openai.com/v1", "--base-url", help="LLM API base URL (OpenAI 兼容)"
    ),
    model: str = typer.Option("gpt-4o", "--model", help="写作模型"),
    check_model: str = typer.Option(None, "--check-model", help="校验模型（默认同写作模型）"),
    language: str = typer.Option("zh", "--language", help="语言"),
) -> None:
    """初始化一个新的小说项目目录。"""
    root = Path(name).resolve()
    if root.exists() and any(root.iterdir()):
        console.print(f"[red]错误：[/red]目录 {root} 非空。")
        raise typer.Exit(code=1)

    paths = scaffold_project(root)
    config = {
        "title": title,
        "author": author,
        "language": language,
        "generation": {
            "temperature": 0.85,
            "max_tokens": 50000,
            "recent_window_chapters": 1,
            "summary_history": 6,
            "auto_consistency_check": True,
            "auto_fix": False,
            "max_fix_rounds": 2,
            "codex_max_tokens": 2000,
            "codex_entry_max_chars": 1500,
        },
    }

    cfg_path = root / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Style bible template — fill in before writing (or run `rimbook style generate`).
    style_path = paths.style_file
    if not style_path.exists():
        style_path.write_text(_STYLE_TEMPLATE, encoding="utf-8")

    console.print(Panel.fit(
        f"[green]已创建项目[/green] [bold]{title}[/bold]\n"
        f"路径：{root}\n\n"
        f"下一步：\n"
        f"  1. 编辑 {cfg_path.name} 填入 API key（或设置环境变量 LLM_API_KEY）\n"
        f"  2. 编辑 outline/style.md 定义写作风格（人称/基调/禁忌）\n"
        f"  3. cd {name} && rimbook codex add  添加实体/设定\n"
        f"  4. rimbook outline synopsis  生成全书梗概",
        title="RimBook 项目初始化完成",
    ))


_STYLE_TEMPLATE = """\
<!-- 写作风格指南（style bible）。写作与修订时会整段注入上下文，模型必须遵守。
     留空的条目可删除；也可以在写完几章后运行 `rimbook style generate` 由 LLM 反推。 -->

## 叙事人称与视角
（示例：第三人称有限视角，单章单视角，视角人物为该章主要行动者。）

## 时态与叙事距离
（示例：过去时；贴近人物内心，但避免直接的心理独白泛滥。）

## 语言基调与句式
（示例：冷峻克制，短句为主；动作场面加快节奏，抒情段落不超过三句。）

## 对话风格
（示例：对话占比约四成；人物用词须符合各自档案中的语言风格画像。）

## 禁忌清单
（示例：禁止翻译腔；禁止"突然""顿时"滥用；禁止以"殊不知"上帝视角插评。）

## 示例段落
（粘贴一到两段最能代表理想文风的段落。）
"""


# ======================================================================
# codex commands
# ======================================================================
codex_app = typer.Typer(help="管理设定集（实体/世界观/地点/势力/物品/时间线）。")
app.add_typer(codex_app, name="codex")


@codex_app.command("add")
def codex_add(
    project: Optional[Path] = typer.Option(None, "--project", "-p", help="项目目录（默认自动探测）"),
    entity_id: str = typer.Option(..., "--id", help="唯一 id（slug）"),
    name: str = typer.Option(..., "--name", help="显示名"),
    type: str = typer.Option(..., "--type", help="类型：character/worldbuilding/location/faction/item/timeline"),
    aliases: str = typer.Option("", "--aliases", help="别名，逗号分隔"),
    tags: str = typer.Option("", "--tags", help="标签，逗号分隔"),
    related: str = typer.Option("", "--related", help="关联实体 id，逗号分隔"),
    body: str = typer.Option("", "--body", help="正文（实体档案/世界观说明等）。留空则打开编辑。"),
) -> None:
    """添加一条设定集条目。"""
    deps = _load_deps(project)
    entry = CodexEntry(
        id=entity_id,
        name=name,
        type=type,
        aliases=[a.strip() for a in aliases.split(",") if a.strip()],
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        related=[r.strip() for r in related.split(",") if r.strip()],
        body=body,
    )
    path = deps.codex.write(entry)
    console.print(f"[green]已写入[/green] {path}")
    if not body:
        console.print(
            f"[yellow]提示：[/yellow]正文为空，请编辑该文件补充实体档案"
            f"（含语言风格画像，用于防 OOC）。"
        )


@codex_app.command("ls")
def codex_ls(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    type: str = typer.Option(None, "--type", help="按类型过滤"),
) -> None:
    """列出设定集条目。"""
    deps = _load_deps(project)
    entries = deps.codex.list_by_type(type) if type else deps.codex.all()
    table = Table(title="设定集")
    table.add_column("类型", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("名称", style="bold")
    table.add_column("别名")
    table.add_column("标签")
    for e in entries:
        table.add_row(
            e.type, e.id, e.name,
            "、".join(e.aliases) if e.aliases else "-",
            "、".join(e.tags) if e.tags else "-",
        )
    console.print(table)


@codex_app.command("show")
def codex_show(
    entry_id: str = typer.Argument(..., help="条目 id"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """查看一条设定集条目的完整内容。"""
    deps = _load_deps(project)
    try:
        entry = deps.codex.read(entry_id)
    except FileNotFoundError:
        console.print(f"[red]未找到[/red] {entry_id}")
        raise typer.Exit(code=1)
    console.print(Panel(entry.body, title=f"[{entry.type}] {entry.name}（{entry.id}）"))


@codex_app.command("dedup")
def codex_dedup(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """检测可能重复/分裂的设定集条目。"""
    from .codex import find_duplicates

    deps = _load_deps(project)
    groups = find_duplicates(deps.codex)
    if not groups:
        console.print("[green]未发现重复条目。[/green]")
        return
    console.print(f"[yellow]发现 {len(groups)} 组可能重复的条目：[/yellow]")
    for g in groups:
        console.print(f"  • 保留 [cyan]{g.canonical_id}[/cyan]，合并 {g.aliases_ids}（{g.reason}）")
    console.print("\n使用 [bold]rimbook codex merge --into <id> --from <id1,id2>[/bold] 合并。")


@codex_app.command("merge")
def codex_merge(
    into: str = typer.Option(..., "--into", help="保留的目标条目 id"),
    from_ids: str = typer.Option(..., "--from", help="要合并的源条目 id，逗号分隔"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """合并重复的设定集条目，并修复章节大纲和实体状态中的引用。"""
    from .codex import merge_entries, merge_duplicate_entities

    deps = _load_deps(project)
    sources = [s.strip() for s in from_ids.split(",") if s.strip()]
    if not sources:
        console.print("[red]错误：[/red]未指定要合并的源条目。")
        raise typer.Exit(code=1)

    # First merge the codex entries.
    try:
        result = merge_entries(deps.codex, into_id=into, from_ids=sources)
    except FileNotFoundError as exc:
        console.print(f"[red]错误：[/red]{exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]已合并[/green] {result.removed_ids} → {into}")

    # Fix references in outlines and entity states.
    if result.remap:
        report = merge_duplicate_entities(
            deps.codex, deps.outline, deps.entity_state
        )
        if report.outlines_fixed:
            console.print(f"[dim]已修复 {report.outlines_fixed} 个章节大纲的实体引用[/dim]")
        if report.states_fixed:
            console.print(f"[dim]已合并 {report.states_fixed} 个实体状态文件[/dim]")


@codex_app.command("migrate")
def codex_migrate(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """迁移旧版数据：将 codex body 中的「当前状态」section 抽取到 EntityState。"""
    from .codex import migrate_state_sections

    deps = _load_deps(project)
    console.print("[cyan]正在扫描 codex 条目…[/cyan]")
    report = migrate_state_sections(deps.codex, deps.entity_state)
    if report.cleaned == 0:
        console.print("[green]所有条目已是最新格式，无需迁移。[/green]")
        return
    console.print(f"[green]完成：[/green]扫描 {report.scanned} 条，清理 {report.cleaned} 条")
    console.print(f"  EntityState 新建 {report.state_created}，更新 {report.state_updated}")
    for detail in report.details:
        console.print(f"  {detail}")


@codex_app.command("migrate-v2")
def codex_migrate_v2(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """将旧版 body 中的 🤖/⚠️ markdown section 迁移到结构化 frontmatter。"""
    from .codex import migrate_to_structured

    deps = _load_deps(project)
    console.print("[cyan]正在扫描 codex 条目…[/cyan]")
    report = migrate_to_structured(deps.codex)
    if report.revelations_extracted == 0 and report.contradictions_extracted == 0:
        console.print("[green]所有条目已是最新结构化格式，无需迁移。[/green]")
        return
    console.print(f"[green]完成：[/green]扫描 {report.scanned} 条")
    console.print(f"  提取发现：{report.revelations_extracted} 条")
    console.print(f"  提取矛盾：{report.contradictions_extracted} 条")
    if report.conflicts_skipped:
        console.print(f"  [yellow]跳过冲突：{report.conflicts_skipped} 条（已有同章节数据）[/yellow]")
    for d in report.details:
        console.print(d)


# ======================================================================
# outline commands
# ======================================================================
outline_app = typer.Typer(help="规划大纲（梗概/卷/章节 beat）。")
app.add_typer(outline_app, name="outline")


@outline_app.command("synopsis")
def outline_synopsis(
    premise: str = typer.Argument(..., help="小说创意/核心设定"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """生成全书梗概（第一阶段）。"""
    deps = _load_deps(project)
    console.print("[cyan]正在生成全书梗概…[/cyan]")
    text = deps.planner.plan_synopsis(premise)
    console.print(Panel(text, title=f"全书梗概 · {deps.config.title}"))
    console.print(f"[green]已保存至[/green] {deps.paths.synopsis_file}")


@outline_app.command("volume")
def outline_volume(
    number: int = typer.Argument(..., help="卷号"),
    title: str = typer.Option("", "--title", "-t"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """规划一卷的大纲。"""
    deps = _load_deps(project)
    console.print(f"[cyan]正在规划第 {number} 卷…[/cyan]")
    vol = deps.planner.plan_volume(number, title=title)
    console.print(Panel(vol.arc, title=f"第 {number} 卷《{vol.title}》大纲"))


@outline_app.command("chapter")
def outline_chapter(
    number: int = typer.Argument(..., help="章节号"),
    volume: Optional[int] = typer.Option(None, "--volume", "-v", help="所属卷号"),
    title: str = typer.Option("", "--title", "-t"),
    hint: str = typer.Option("", "--hint", help="给规划的额外提示"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """规划一章的 beat（要发生什么）。"""
    deps = _load_deps(project)
    console.print(f"[cyan]正在规划第 {number} 章 beat…[/cyan]")
    result = deps.planner.plan_chapter_detailed(
        number, volume=volume, title=title, hint=hint
    )
    ch = result.chapter
    _print_chapter_plan(ch, deps)
    if result.id_warnings:
        console.print("[yellow]实体 id 提示：[/yellow]")
        for w in result.id_warnings:
            console.print(f"  • {w}")
    if result.new_entity_ids:
        console.print(
            f"[dim]本章首次出现的实体（{len(result.new_entity_ids)} 个），"
            f"写作后会自动创建占位 codex 条目。[/dim]"
        )


def _print_chapter_plan(ch, deps) -> None:
    console.print(Panel(
        f"涉及实体：{'、'.join(ch.all_entities()) or '（无）'}\n"
        f"标签：{'、'.join(ch.tags) or '（无）'}\n\n"
        + ("\n".join(
            f"[bold]场景{i}[/bold] {b.goal}"
            + (f"（冲突：{b.conflict}）" if b.conflict else "")
            + (f" → {b.outcome}" if b.outcome else "")
            for i, b in enumerate(ch.beats, 1)
        ) or "（无具体场景计划）"),
        title=f"第 {ch.number} 章《{ch.title}》beat",
    ))
    console.print(f"[green]已保存至[/green] {deps.paths.chapter_outline(ch.number)}")


# ======================================================================
# write / check commands
# ======================================================================
@app.command()
def write(
    number: int = typer.Argument(..., help="章节号"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    check: Optional[bool] = typer.Option(
        None, "--check/--no-check", help="是否在写作后跑一致性校验（默认读配置）"
    ),
    fix: Optional[bool] = typer.Option(
        None, "--fix/--no-fix", help="是否自动修复（默认读配置）"
    ),
) -> None:
    """生成一章正文（走完整流水线：组装上下文→写作→摘要→实体状态）。"""
    deps = _load_deps(project)
    console.print(f"[cyan]正在生成第 {number} 章正文…[/cyan]")
    result = deps.writer.write(number)
    console.print(f"[green]草稿已写入[/green] {result.draft_path}")
    if result.summary:
        console.print(Panel(result.summary, title="本章摘要"))
    if result.entities_tracked:
        console.print(f"[dim]已更新实体状态：{'、'.join(result.entities_tracked)}[/dim]")
    if result.usage:
        console.print(f"[dim]tokens: {result.usage}[/dim]")

    # Enrichment results.
    if result.enrichment:
        _print_enrichment(result.enrichment)

    # Consistency check / auto-fix.
    do_check = deps.config.generation.auto_consistency_check if check is None else check
    if do_check:
        _run_check_and_maybe_fix(deps, number, auto_fix=fix)


@app.command()
def check(
    number: int = typer.Argument(..., help="章节号"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    fix: bool = typer.Option(False, "--fix", help="自动修复发现的问题"),
) -> None:
    """单独对一章草稿做一致性校验。"""
    deps = _load_deps(project)
    _run_check_and_maybe_fix(deps, number, auto_fix=fix, override_check=True)


@app.command()
def revise(
    number: int = typer.Argument(..., help="章节号"),
    instructions: str = typer.Option("", "--instructions", "-i", help="修订要求"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """根据要求重写/修订一章草稿（保留原有上下文一致性）。"""
    deps = _load_deps(project)
    console.print(f"[cyan]正在修订第 {number} 章…[/cyan]")
    result = deps.writer.revise(number, instructions=instructions)
    console.print(f"[green]已更新草稿[/green] {result.draft_path}")
    if result.summary:
        console.print(Panel(result.summary, title="修订后摘要"))


@app.command()
def summary(
    number: int = typer.Argument(..., help="章节号"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """重新生成一章的摘要（用于修正/补全）。"""
    deps = _load_deps(project)
    path = deps.paths.draft_file(number)
    if not path.exists():
        console.print(f"[red]未找到第 {number} 章草稿[/red]")
        raise typer.Exit(code=1)
    text = path.read_text(encoding="utf-8").strip()
    console.print(f"[cyan]正在生成第 {number} 章摘要…[/cyan]")
    sm = deps.summarizer.summarize(number, text)
    console.print(Panel(sm, title="章节摘要"))
    console.print(f"[green]已写回[/green] {deps.paths.chapter_outline(number)}")


@app.command()
def enrich(
    number: int = typer.Argument(..., help="章节号"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览变更不写入"),
) -> None:
    """对已写的章节草稿运行 LLM 设定集扩充（发现新实体、更新档案、标记矛盾）。"""
    deps = _load_deps(project)

    # Read the draft.
    draft_path = deps.paths.draft_file(number)
    if not draft_path.exists():
        console.print(f"[red]未找到第 {number} 章草稿[/red]")
        raise typer.Exit(code=1)
    draft = draft_path.read_text(encoding="utf-8").strip()

    chapter = deps.outline.read_chapter(number)
    if chapter is None:
        console.print(f"[red]第 {number} 章无章节规划[/red]")
        raise typer.Exit(code=1)

    from .pipeline.post_write import PostWritePipeline

    enricher = PostWritePipeline(
        llm=deps.llm,
        prompts=deps.prompts,
        codex=deps.codex,
        entity_state=deps.entity_state,
        summarizer=deps.summarizer,
        generation=deps.config.generation,
        trace=deps.trace,
        project_name=deps.project_dir.name,
    )

    if dry_run:
        console.print("[cyan]正在分析（dry-run 模式）…[/cyan]")
        data = enricher.enrich_codex(number, draft, chapter.all_entities())
        console.print(f"[yellow]将创建 {len(data.get('new_entities', []))} 个新实体[/yellow]")
        for ne in data.get("new_entities") or []:
            console.print(f"  • [green]{ne.get('id')}[/green]: {ne.get('name')} [{ne.get('type')}]")
        console.print(f"[yellow]将更新 {len(data.get('updates', []))} 个已有实体[/yellow]")
        for up in data.get("updates") or []:
            console.print(f"  • {up.get('id')}")
            if up.get("contradictions"):
                for c in up["contradictions"]:
                    console.print(f"    [red]⚠ {c}[/red]")
        return

    console.print(f"[cyan]正在对第 {number} 章进行设定集扩充…[/cyan]")
    enrich_result = enricher.run(number, draft, chapter, enrich=True)
    _print_enrichment(enrich_result)


def _print_enrichment(result) -> None:
    """Print enrichment results in a readable format."""
    if result.entities_created:
        console.print(f"[green]新增实体（{len(result.entities_created)} 个）：[/green]")
        for c in result.entities_created:
            console.print(f"  • {c.detail}")
    if result.entities_updated:
        console.print(f"[cyan]更新实体（{len(result.entities_updated)} 个）：[/cyan]")
        for c in result.entities_updated:
            console.print(f"  • {c.detail}")
    if result.contradictions:
        console.print(f"[red]发现矛盾（{len(result.contradictions)} 处）：[/red]")
        for c in result.contradictions:
            console.print(f"  • [{c.entity_id}] {c.detail}")
    if result.thread_changes and any(result.thread_changes.values()):
        tc = result.thread_changes
        console.print(
            f"[dim]情节线索：新埋 {tc.get('created', 0)}，"
            f"推进 {tc.get('progressed', 0)}，回收 {tc.get('resolved', 0)}[/dim]"
        )
    if result.summary:
        console.print(f"[dim]{result.summary}[/dim]")


def _run_check_and_maybe_fix(
    deps: Deps, number: int, *, auto_fix: Optional[bool], override_check: bool = False
) -> None:
    do_fix = deps.config.generation.auto_fix if auto_fix is None else auto_fix
    max_rounds = deps.config.generation.max_fix_rounds if do_fix else 0

    if do_fix and max_rounds > 0:
        console.print(f"[cyan]校验中（最多 {max_rounds} 轮自动修复）…[/cyan]")

        def apply_fix(text: str, issues_blob: str) -> str:
            console.print(f"[yellow]发现需修订的问题，正在定点修复…[/yellow]")
            # Minimal-fix path: patch only the problematic passages instead of
            # re-writing the whole chapter (preserves voice; see fix_* prompts).
            return deps.writer.apply_minimal_fix(number, text, issues_blob)

        report = deps.checker.check_and_fix(number, max_rounds=max_rounds, apply_fix=apply_fix)
    else:
        console.print("[cyan]一致性校验中…[/cyan]")
        report = deps.checker.check(number)

    _print_check_report(report)


def _print_check_report(report) -> None:
    color = {"通过": "green", "需修订": "yellow", "严重问题": "red"}.get(report.overall, "white")
    console.print(f"[{color}]校验结论：{report.overall}[/{color}]  {report.summary}")
    if report.rounds:
        console.print(f"[dim]自动修复轮数：{report.rounds}[/dim]")
    if report.issues:
        table = Table(title="发现的问题")
        table.add_column("级别", style="bold")
        table.add_column("类别")
        table.add_column("描述")
        table.add_column("建议", style="dim")
        for iss in report.issues:
            sev_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(
                iss.severity, "white"
            )
            table.add_row(
                f"[{sev_color}]{iss.severity}[/{sev_color}]",
                iss.category,
                iss.description,
                iss.suggestion or "-",
            )
        console.print(table)
    else:
        console.print("[green]未发现一致性问题。[/green]")


# ======================================================================
# style / recap / threads / review commands
# ======================================================================
style_app = typer.Typer(help="管理写作风格指南（style bible）。")
app.add_typer(style_app, name="style")


@style_app.command("show")
def style_show(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """查看当前的写作风格指南。"""
    deps = _load_deps(project)
    text = deps.outline.read_style()
    if not text:
        console.print(
            "[yellow]尚无风格指南。[/yellow]编辑 outline/style.md，"
            "或运行 [bold]rimbook style generate[/bold] 从已写章节反推。"
        )
        return
    console.print(Panel(text, title="写作风格指南"))


@style_app.command("generate")
def style_generate(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    chapters: int = typer.Option(3, "--chapters", "-n", help="取最近几章正文作为样本"),
) -> None:
    """从已写章节反推写作风格指南（会覆盖 outline/style.md）。"""
    deps = _load_deps(project)
    recent = deps.window.recent(chapters, before=10**9)
    if not recent:
        console.print("[red]尚无已写章节，无法反推风格。[/red]请先手动编辑 outline/style.md。")
        raise typer.Exit(code=1)
    samples = "\n\n".join(
        f"--- 第 {ch.number} 章节选 ---\n{ch.text[:3000]}" for ch in recent
    )
    console.print(f"[cyan]正在从 {len(recent)} 章样本提炼风格指南…[/cyan]")
    messages = deps.llm.as_chat(
        system=deps.prompts.style_generate_system,
        user=deps.prompts.style_generate_user.format(
            title=deps.config.title, samples=samples,
        ),
    )
    with deps.trace.begin("style", project=deps.project_dir.name) as t:
        result = deps.llm.generate(messages, temperature=0.3)
        t.record(messages, result)
    text = result.content.strip()
    deps.outline.write_style(text)
    console.print(Panel(text, title="写作风格指南"))
    console.print(f"[green]已保存至[/green] {deps.paths.style_file}")


recap_app = typer.Typer(help="维护分层记忆（卷情节回顾 / 全书至今故事线）。")
app.add_typer(recap_app, name="recap")


@recap_app.command("volume")
def recap_volume(
    number: int = typer.Argument(..., help="卷号"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """（重新）生成一卷的实际剧情回顾。"""
    deps = _load_deps(project)
    console.print(f"[cyan]正在生成第 {number} 卷情节回顾…[/cyan]")
    try:
        recap = deps.summarizer.summarize_volume(number)
    except FileNotFoundError as exc:
        console.print(f"[red]错误：[/red]{exc}")
        raise typer.Exit(code=1)
    if not recap:
        console.print("[yellow]该卷尚无带摘要的章节，未生成回顾。[/yellow]")
        return
    console.print(Panel(recap, title=f"第 {number} 卷情节回顾"))


@recap_app.command("story")
def recap_story(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    upto: Optional[int] = typer.Option(None, "--upto", help="截至章号（默认最新章）"),
) -> None:
    """（重新）生成滚动的「全书至今」故事线。"""
    deps = _load_deps(project)
    last = upto if upto is not None else deps.outline.last_chapter_number()
    if last <= 0:
        console.print("[yellow]尚无章节。[/yellow]")
        return
    console.print(f"[cyan]正在更新全书至今故事线（截至第 {last} 章）…[/cyan]")
    text = deps.summarizer.update_story_so_far(last)
    if not text:
        console.print("[yellow]无新增章节摘要，故事线未变化。[/yellow]")
        return
    console.print(Panel(text, title=f"全书至今（截至第 {last} 章）"))
    console.print(f"[green]已保存至[/green] {deps.paths.story_so_far_file}")


threads_app = typer.Typer(help="查看情节线索账本（伏笔/悬念/承诺）。")
app.add_typer(threads_app, name="threads")


@threads_app.command("ls")
def threads_ls(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    all: bool = typer.Option(False, "--all", "-a", help="包含已回收的线索"),
) -> None:
    """列出情节线索。"""
    deps = _load_deps(project)
    items = deps.threads.all() if all else deps.threads.open_threads()
    if not items:
        console.print("[dim]账本为空（线索在写作后自动抽取，或手动编辑 state/threads.yaml）。[/dim]")
        return
    table = Table(title="情节线索账本")
    table.add_column("ID", style="dim")
    table.add_column("类型", style="cyan")
    table.add_column("状态")
    table.add_column("埋设章", justify="right")
    table.add_column("预计回收", justify="right")
    table.add_column("描述")
    type_labels = {"foreshadow": "伏笔", "suspense": "悬念", "promise": "承诺"}
    status_style = {"open": "yellow", "progressed": "cyan", "resolved": "green"}
    for t in items:
        table.add_row(
            t.id,
            type_labels.get(t.type, t.type),
            f"[{status_style.get(t.status, 'white')}]{t.status}[/]",
            str(t.planted_chapter),
            str(t.expected_resolve_chapter or "-"),
            t.description,
        )
    console.print(table)


@app.command()
def review(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
    volume: Optional[int] = typer.Option(None, "--volume", "-v", help="审阅某一卷"),
    from_chapter: Optional[int] = typer.Option(None, "--from", help="起始章号"),
    to_chapter: Optional[int] = typer.Option(None, "--to", help="结束章号"),
) -> None:
    """宏观编辑审阅：通读多章，报告节奏/重复桥段/角色声音趋同等问题（只报告不改稿）。"""
    deps = _load_deps(project)
    chapters = deps.outline.list_chapters()
    if volume is not None:
        chapters = [c for c in chapters if c.volume == volume]
        scope = f"第 {volume} 卷"
    else:
        lo = from_chapter or 1
        hi = to_chapter or deps.outline.last_chapter_number()
        chapters = [c for c in chapters if lo <= c.number <= hi]
        scope = f"第 {lo}-{hi} 章"
    chapters = [c for c in chapters if c.summary.strip()]
    if not chapters:
        console.print("[yellow]范围内没有带摘要的已写章节。[/yellow]")
        return

    digest_lines = []
    for c in chapters:
        extras = []
        if c.tension:
            extras.append(f"张力{c.tension}/5")
        if c.purpose:
            extras.append(c.purpose)
        if c.value_shift:
            extras.append(f"价值转变：{c.value_shift}")
        extra_str = f"（{'；'.join(extras)}）" if extras else ""
        digest_lines.append(f"第 {c.number} 章《{c.title}》{extra_str}：{c.summary.strip()}")
    digest = "\n".join(digest_lines)

    samples: list[str] = []
    for c in chapters:
        path = deps.paths.draft_file(c.number)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        head = text[:400]
        tail = text[-400:] if len(text) > 800 else ""
        block = f"--- 第 {c.number} 章开头 ---\n{head}"
        if tail:
            block += f"\n--- 第 {c.number} 章结尾 ---\n{tail}"
        samples.append(block)
    prose_samples = "\n\n".join(samples) or "（无正文抽样）"

    console.print(f"[cyan]正在宏观审阅 {scope}（{len(chapters)} 章）…[/cyan]")
    messages = deps.llm.as_chat(
        system=deps.prompts.macro_review_system,
        user=deps.prompts.macro_review_user.format(
            scope=scope, chapter_digest=digest, prose_samples=prose_samples,
        ),
    )
    with deps.trace.begin("macro_review", project=deps.project_dir.name) as t:
        result = deps.llm.generate(
            messages,
            temperature=0.3,
            model=deps.llm.config.effective_check_model,
        )
        t.record(messages, result)
    report = result.content.strip()
    console.print(Panel(report, title=f"宏观审阅报告 · {scope}"))

    import time as _time
    deps.paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    slug = f"vol{volume}" if volume is not None else f"ch{chapters[0].number}-{chapters[-1].number}"
    out = deps.paths.reviews_dir / f"{_time.strftime('%Y%m%d-%H%M%S')}-{slug}.md"
    out.write_text(f"# 宏观审阅报告 · {scope}\n\n{report}\n", encoding="utf-8")
    console.print(f"[green]报告已保存至[/green] {out}")


# ======================================================================
# status / vector / snapshot commands
# ======================================================================
@app.command()
def status(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """查看项目进度总览。"""
    deps = _load_deps(project)
    console.print(Panel.fit(
        f"[bold]{deps.config.title}[/bold]"
        + (f"  by {deps.config.author}" if deps.config.author else ""),
        title="RimBook 项目",
    ))
    synopsis = deps.outline.read_synopsis().strip()
    console.print(f"全书梗概：[{'green' if synopsis else 'red'}]{'有' if synopsis else '无'}[/]")
    volumes = deps.outline.list_volumes()
    chapters = deps.outline.list_chapters()
    console.print(f"卷目数：{len(volumes)}")
    console.print(f"章节 beat 数：{len(chapters)}")
    drafts = list(deps.paths.drafts_dir.glob("ch*.md"))
    console.print(f"已写草稿数：{len(drafts)}")
    entities = deps.codex.all()
    console.print(f"设定集条目数：{len(entities)}")
    table = Table(title="章节进度")
    table.add_column("章")
    table.add_column("标题")
    table.add_column("卷")
    table.add_column("beat", justify="right")
    table.add_column("摘要")
    table.add_column("草稿")
    draft_nums = {_draft_num(p) for p in drafts}
    for ch in chapters:
        has_draft = "[green]是[/green]" if ch.number in draft_nums else "[dim]否[/dim]"
        table.add_row(
            str(ch.number),
            ch.title or "-",
            str(ch.volume) if ch.volume else "-",
            str(len(ch.beats)),
            "有" if ch.summary.strip() else "[dim]无[/dim]",
            has_draft,
        )
    if chapters:
        console.print(table)


def _draft_num(path: Path) -> int | None:
    stem = path.stem
    if stem.startswith("ch") and stem[2:].isdigit():
        return int(stem[2:])
    return None


vector_app = typer.Typer(help="向量索引维护（增强检索）。")
app.add_typer(vector_app, name="vector")


@vector_app.command("rebuild")
def vector_rebuild(
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """从源文件重建向量索引。"""
    deps = _load_deps(project)
    try:
        from .retrieval import VectorIndexer
    except ImportError as exc:
        console.print(f"[red]向量检索不可用：[/red]{exc}")
        raise typer.Exit(code=1)
    indexer = VectorIndexer(deps.paths, deps.llm)
    console.print("[cyan]正在重建向量索引…[/cyan]")
    counts = indexer.rebuild(codex=deps.codex, outline=deps.outline)
    console.print(f"[green]完成[/green]：codex {counts['codex']} 条，summaries {counts['summaries']} 条")


@vector_app.command("query")
def vector_query(
    text: str = typer.Argument(..., help="查询文本"),
    k: int = typer.Option(5, "--k", "-k", help="返回数量"),
    collection: str = typer.Option("codex", "--collection", "-c", help="codex 或 summaries"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """测试向量检索。"""
    deps = _load_deps(project)
    try:
        from .retrieval import VectorRetriever
    except ImportError as exc:
        console.print(f"[red]向量检索不可用：[/red]{exc}")
        raise typer.Exit(code=1)
    retriever = VectorRetriever(deps.paths, deps.llm)
    hits = retriever.query(text, k=k, collection=collection)
    if not hits:
        console.print("[yellow]无结果（索引可能为空，先运行 rebuild）。[/yellow]")
        return
    for hit in hits:
        dist = hit.get("distance")
        dist_s = f"{dist:.3f}" if dist is not None else "?"
        console.print(f"[cyan]{hit['id']}[/cyan] (距离 {dist_s})")


@app.command()
def snapshot(
    label: str = typer.Option("manual", "--label", "-l", help="快照标签"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """给当前项目打一个版本快照（用于回滚）。"""
    import time
    deps = _load_deps(project)
    ts = time.strftime("%Y%m%d-%H%M%S")
    snap_dir = deps.paths.versions_dir / f"{ts}-{label}"
    snap_dir.mkdir(parents=True, exist_ok=True)
    # Copy everything except the versions dir itself.
    for item in deps.project_dir.iterdir():
        if item.name == ".versions":
            continue
        _copy_tree(item, snap_dir / item.name)
    console.print(f"[green]快照已保存：[/green] {snap_dir}")


@app.command()
def rollback(
    snapshot_name: str = typer.Argument(..., help="快照目录名（见 .versions/）"),
    project: Optional[Path] = typer.Option(None, "--project", "-p"),
) -> None:
    """从快照回滚项目（会覆盖当前内容，请先确认）。"""
    deps = _load_deps(project)
    snap_dir = deps.paths.versions_dir / snapshot_name
    if not snap_dir.exists():
        console.print(f"[red]快照不存在：[/red]{snap_dir}")
        raise typer.Exit(code=1)
    typer.confirm(f"将用 {snap_dir} 覆盖当前项目，确定吗？", abort=True)
    # Wipe current content (except versions) and copy from snapshot.
    for item in deps.project_dir.iterdir():
        if item.name == ".versions":
            continue
        _remove(item)
    for item in snap_dir.iterdir():
        _copy_tree(item, deps.project_dir / item.name)
    console.print(f"[green]已回滚到[/green] {snap_dir}")


def _copy_tree(src: Path, dst: Path) -> None:
    import shutil
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def _remove(p: Path) -> None:
    import shutil
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()


@app.command()
def version() -> None:
    """显示版本号。"""
    console.print(f"RimBook v{__version__}")


if __name__ == "__main__":
    app()
