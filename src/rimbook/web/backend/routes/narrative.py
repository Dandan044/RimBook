"""Narrative-management routes — style bible, plot threads, hierarchical
memory (story-so-far / volume recaps), and macro editorial review."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import ProjectDeps, get_project_deps
from ..tasks import task_registry

router = APIRouter(prefix="/api/projects/{project_id}", tags=["narrative"])


# ---- style bible ----

class StyleIn(BaseModel):
    text: str


@router.get("/style")
def get_style(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    return {"text": deps.outline.read_style()}


@router.put("/style")
def update_style(req: StyleIn, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    deps.outline.write_style(req.text)
    return {"ok": True}


class StyleGenerateReq(BaseModel):
    chapters: int = 3


@router.post("/style/generate")
def generate_style(
    project_id: str,
    req: StyleGenerateReq,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """LLM-infer the style bible from recent chapter prose (overwrites style.md)."""
    recent = deps.window.recent(max(1, req.chapters), before=10**9)
    if not recent:
        raise HTTPException(400, "尚无已写章节，无法反推风格；请先手动编辑风格指南。")
    samples = "\n\n".join(
        f"--- 第 {ch.number} 章节选 ---\n{ch.text[:3000]}" for ch in recent
    )
    task_registry.register(project_id, "style_generate", None, "正在提炼风格指南…")
    try:
        synopsis = ""
        try:
            synopsis = deps.outline.read_synopsis().strip()
        except Exception:
            synopsis = ""
        messages = deps.llm.as_chat(
            system=deps.prompts.style_generate_system,
            user=deps.prompts.style_generate_user.format(
                title=deps.config.title,
                samples=samples,
                synopsis=synopsis or "（无）",
            ),
        )
        with deps.trace.begin("style", project=deps.project_dir.name) as t:
            result = deps.llm.generate(messages, temperature=0.3)
            t.record(messages, result)
        text = result.content.strip()
        deps.outline.write_style(text)
        return {"text": text}
    finally:
        task_registry.unregister(project_id, "style_generate", None)


# ---- plot threads ----

@router.get("/threads")
def list_threads(
    include_resolved: bool = True,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    items = deps.threads.all() if include_resolved else deps.threads.open_threads()
    return {
        "threads": [
            {
                "id": t.id,
                "description": t.description,
                "type": t.type,
                "status": t.status,
                "planted_chapter": t.planted_chapter,
                "expected_resolve_chapter": t.expected_resolve_chapter,
                "resolved_chapter": t.resolved_chapter,
                "updates": [{"chapter": u.chapter, "note": u.note} for u in t.updates],
            }
            for t in items
        ]
    }


class ThreadUpdateReq(BaseModel):
    description: str | None = None
    type: str | None = None
    status: str | None = None
    expected_resolve_chapter: int | None = None


@router.put("/threads/{thread_id}")
def update_thread(
    thread_id: str,
    req: ThreadUpdateReq,
    deps: ProjectDeps = Depends(get_project_deps),
) -> dict:
    """Manually edit a thread (description / type / status / expected chapter)."""
    store = deps.threads
    threads = store.all()
    target = next((t for t in threads if t.id == thread_id), None)
    if target is None:
        raise HTTPException(404, f"线索 {thread_id} 不存在")
    if req.description is not None:
        target.description = req.description
    if req.type is not None:
        from rimbook.memory.threads import THREAD_TYPES

        if req.type not in THREAD_TYPES:
            raise HTTPException(400, f"非法类型：{req.type}")
        target.type = req.type
    if req.status is not None:
        from rimbook.memory.threads import THREAD_STATUSES

        if req.status not in THREAD_STATUSES:
            raise HTTPException(400, f"非法状态：{req.status}")
        target.status = req.status
    if "expected_resolve_chapter" in req.model_fields_set:
        target.expected_resolve_chapter = req.expected_resolve_chapter
    store.save_all(threads)
    return {"ok": True}


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    store = deps.threads
    threads = store.all()
    kept = [t for t in threads if t.id != thread_id]
    if len(kept) == len(threads):
        raise HTTPException(404, f"线索 {thread_id} 不存在")
    store.save_all(kept)
    return {"ok": True}


# ---- hierarchical memory ----

@router.get("/recap/story")
def get_story_so_far(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    text, upto = deps.outline.read_story_so_far()
    return {"text": text, "upto_chapter": upto}


@router.post("/recap/story")
def refresh_story_so_far(project_id: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """Refresh the rolling story-so-far up to the latest chapter."""
    last = deps.outline.last_chapter_number()
    if last <= 0:
        raise HTTPException(400, "尚无章节")
    task_registry.register(project_id, "recap_story", None, "正在更新全书故事线…")
    try:
        text = deps.summarizer.update_story_so_far(last)
        _, upto = deps.outline.read_story_so_far()
        return {"text": text, "upto_chapter": upto}
    finally:
        task_registry.unregister(project_id, "recap_story", None)


@router.post("/recap/volume/{number}")
def refresh_volume_recap(
    project_id: str, number: int, deps: ProjectDeps = Depends(get_project_deps)
) -> dict:
    """(Re)generate the realized recap of one volume."""
    task_registry.register(project_id, "recap_volume", number, "正在生成卷回顾…")
    try:
        recap = deps.summarizer.summarize_volume(number)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    finally:
        task_registry.unregister(project_id, "recap_volume", number)
    if not recap:
        raise HTTPException(400, "该卷尚无带摘要的章节，无法生成回顾")
    return {"recap": recap}


# ---- macro editorial review ----

class ReviewReq(BaseModel):
    volume: int | None = None
    from_chapter: int | None = None
    to_chapter: int | None = None


@router.post("/review")
def run_macro_review(
    project_id: str, req: ReviewReq, deps: ProjectDeps = Depends(get_project_deps)
) -> dict:
    """Run a macro editorial review over a volume or chapter range."""
    chapters = deps.outline.list_chapters()
    if req.volume is not None:
        chapters = [c for c in chapters if c.volume == req.volume]
        scope = f"第 {req.volume} 卷"
        slug = f"vol{req.volume}"
    else:
        lo = req.from_chapter or 1
        hi = req.to_chapter or deps.outline.last_chapter_number()
        chapters = [c for c in chapters if lo <= c.number <= hi]
        scope = f"第 {lo}-{hi} 章"
        slug = f"ch{lo}-{hi}"
    chapters = [c for c in chapters if c.summary.strip()]
    if not chapters:
        raise HTTPException(400, "范围内没有带摘要的已写章节")

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

    synopsis = ""
    try:
        synopsis = deps.outline.read_synopsis().strip()
    except Exception:
        synopsis = ""
    task_registry.register(project_id, "review", None, f"正在宏观审阅 {scope}…")
    try:
        messages = deps.llm.as_chat(
            system=deps.prompts.macro_review_system,
            user=deps.prompts.macro_review_user.format(
                scope=scope, synopsis=synopsis or "（暂无全书梗概）",
                chapter_digest=digest, prose_samples=prose_samples,
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
    finally:
        task_registry.unregister(project_id, "review", None)

    deps.paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.md"
    out = deps.paths.reviews_dir / name
    out.write_text(f"# 宏观审阅报告 · {scope}\n\n{report}\n", encoding="utf-8")

    return {"scope": scope, "report": report, "saved_as": name, "chapters": len(chapters)}


@router.get("/reviews")
def list_reviews(deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    """List saved macro-review reports (newest first)."""
    d = deps.paths.reviews_dir
    if not d.exists():
        return {"reviews": []}
    out = []
    for f in sorted(d.glob("*.md"), reverse=True):
        out.append({"name": f.name})
    return {"reviews": out}


@router.get("/reviews/{name}")
def get_review(name: str, deps: ProjectDeps = Depends(get_project_deps)) -> dict:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    f = deps.paths.reviews_dir / name
    if not f.exists():
        raise HTTPException(404, f"报告 {name} 不存在")
    return {"name": name, "text": f.read_text(encoding="utf-8")}
