"""E2E: create a temp novel project and run full plan_volume_v2 (5 steps).

Usage (from repo root):
  python scripts/e2e_volume_framework.py

Uses workspace `.rimbook.yaml` for LLM credentials. Seeds a small planning
codex so Step1 can exercise full-setting framework generation without a long
foundation run.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rimbook.cli import Deps  # noqa: E402
from rimbook.planning_entities import (  # noqa: E402
    PlanningCodexEntry,
    PlanningEntityStore,
    PlanningRelationship,
)
from rimbook.project import scaffold_project  # noqa: E402

PROJECT = ROOT / "e2e-volume-fw-test"
LOG = PROJECT / "e2e_run.log"


def _log(msg: str) -> None:
    line = msg.rstrip()
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def reset_project() -> Path:
    if PROJECT.exists():
        shutil.rmtree(PROJECT)
    paths = scaffold_project(PROJECT, exist_ok=True)
    cfg = PROJECT / "config.yaml"
    cfg.write_text(
        "title: E2E写作框架验证\n"
        "author: rimbook-e2e\n"
        "language: zh\n"
        "generation:\n"
        "  temperature: 1.0\n"
        "  max_tokens: 50000\n"
        "world_expansion:\n"
        "  coefficient: 1\n",
        encoding="utf-8",
    )
    return paths


def seed_codex(paths) -> None:
    store = PlanningEntityStore(paths)
    entries = [
        PlanningCodexEntry(
            id="char_lin_mo",
            name="林默",
            type="character",
            surface_summary="旧案调查员，表面克制冷静。",
            secret_truth="他怀疑父亲与旧案有关，却不敢深挖。",
            narrative_role="主角 / 调查视角",
            reveal_strategy="开篇以现场勘查登场",
            detail=(
                "## 出身\n林默在雾城长大，父亲曾是档案局职员，失踪于十年前的灰蚀事件。"
                "母亲临终只留下一句「活下去」。\n\n"
                "## 动机\n表面上他追查失踪人口案，私下想证明父亲并非叛徒。"
                "习惯把情绪压进程序与证据链，害怕被情绪带偏。\n\n"
                "## 能力与限制\n擅长档案交叉比对与现场重建；不善公关，容易被体制程序卡住。"
            ),
            details={"inner_need": "确认自己没有重蹈父亲覆辙", "fear": "真相证明自己也是共犯"},
            source="manual",
        ),
        PlanningCodexEntry(
            id="char_zhou_lan",
            name="周岚",
            type="character",
            surface_summary="档案局副科长，礼貌疏离。",
            secret_truth="她藏着半份能洗清林默父亲的档案。",
            narrative_role="知情者 / 压力源",
            reveal_strategy="以审批官身份介入调查",
            detail=(
                "## 立场\n周岚站在体制内侧，相信「过早公开会毁更多人」。"
                "她与林默父亲曾是同事，欠过人情。\n\n"
                "## 手段\n善用程序拖延与信息分级；极少直接撒谎，但从不给足关键页。"
            ),
            details={"fear": "档案公开导致整层系统坍塌"},
            source="manual",
        ),
        PlanningCodexEntry(
            id="loc_hope_gate",
            name="希望之门",
            type="location",
            surface_summary="雾城权力与档案中枢要塞。",
            secret_truth="地下三层仍封存未登记的灰蚀样本。",
            narrative_role="主舞台",
            reveal_strategy="调查必须进入门内办公区",
            detail=(
                "## 空间结构\n地面是公开接待与会议层；二层为档案审批；三层封锁。"
                "通行靠磁卡与双人联签，公开对质成本极高。\n\n"
                "## 氛围\n灯管冷白，走廊回声大，适合信息差与程序施压。"
            ),
            details={"strategic_value": "权力与证据的交汇点"},
            source="manual",
        ),
        PlanningCodexEntry(
            id="world_gray_corrosion",
            name="灰蚀",
            type="worldbuilding",
            surface_summary="一种沿金属与混凝土扩散的污染现象。",
            secret_truth="灰蚀会改写档案磁性介质，使部分记录不可恢复。",
            narrative_role="世界压迫感 / 时限",
            reveal_strategy="通过门外周边封锁新闻侧面露出",
            detail=(
                "## 规则\n灰蚀沿导电与潮湿表面扩张；接触越久，短期记忆越易断片。"
                "门外已设三道隔离环，每天收缩约五十米。\n\n"
                "## 社会影响\n物资配给与通行许可都与「距灰蚀距离」挂钩，制造集体焦虑。"
            ),
            source="manual",
        ),
        PlanningCodexEntry(
            id="item_old_dossier",
            name="旧档残页",
            type="item",
            surface_summary="一张被撕去半边的审批单复印件。",
            secret_truth="残页背面有林默父亲的联签笔迹。",
            narrative_role="物证麦高芬",
            reveal_strategy="由周岚「不慎」露出一角",
            detail="纸张发黄，盖着希望之门二层红色骑缝章；缺的半边正是关键人名。",
            source="manual",
        ),
    ]
    for entry in entries:
        store.save_entry(entry)
    store.save_relationship(
        PlanningRelationship(
            id="rel_lin_zhou",
            source_id="char_lin_mo",
            target_id="char_zhou_lan",
            relationship_type="对立合作",
            conflict="是否交出完整档案",
            stakes="父亲名誉与体制稳定",
        )
    )
    store.save_relationship(
        PlanningRelationship(
            id="rel_lin_gate",
            source_id="char_lin_mo",
            target_id="loc_hope_gate",
            relationship_type="位于",
            conflict="准入权限不足",
        )
    )


def seed_synopsis(deps: Deps) -> None:
    text = (
        "雾城边缘，灰蚀逐年内逼。青年调查员林默接手一桩失踪旧案，"
        "线索指向权力中枢「希望之门」。档案局副科长周岚掌握关键材料却拒绝全盘公开。"
        "林默必须在程序、人情与灰蚀时限之间做出选择：揭开真相，或保住更多人的表面安全。"
        "全书主题是真相的代价与体制内的信息伦理；基调冷峻克制，近距离第三人称跟随林默。"
    )
    deps.outline.write_synopsis(text)


def run_volume(deps: Deps) -> list[dict]:
    events: list[dict] = []
    t0 = time.time()
    for event in deps.planner.plan_volume_v2(1, title="门内的刀"):
        events.append(event)
        kind = event.get("event")
        data = event.get("data") or {}
        if kind == "step":
            _log(
                f"[step {data.get('step')}] {data.get('status')}: "
                f"{data.get('message', '')}"
            )
            if data.get("status") == "done" and data.get("step") == 1:
                fw = data.get("framework") or {}
                _log(f"  framework cast={fw.get('cast')} stages={fw.get('stages')}")
                _log(f"  casting_note={fw.get('casting_note', '')[:120]}")
            if data.get("status") == "done" and data.get("step") == 2:
                vol = data.get("volume") or {}
                _log(
                    f"  volume title={vol.get('title')} "
                    f"chapters={vol.get('chapter_count')} "
                    f"arc_len={len(vol.get('arc') or '')}"
                )
        elif kind == "progress":
            _log(f"[progress] {data.get('message', data)}")
        elif kind == "error":
            _log(f"[error] {data}")
            raise RuntimeError(data)
    _log(f"pipeline wall time: {time.time() - t0:.1f}s")
    return events


def verify(deps: Deps) -> None:
    errors: list[str] = []

    fw = deps.outline.load_volume_framework(1)
    if fw is None:
        errors.append("缺少 vol01.framework.yaml")
    else:
        if not fw.cast:
            errors.append("framework.cast 为空")
        if not fw.reader_lens.current_perspective:
            errors.append("reader_lens.current_perspective 为空")
        if not fw.craft_focus.conflict and not fw.craft_focus.suspense:
            errors.append("craft_focus 几乎为空")
        # known ids only
        known = {e.id for e in PlanningEntityStore(deps.paths).list_entries()}
        bad = [c.id for c in fw.cast if c.id not in known]
        if bad:
            errors.append(f"framework cast 含未知 id: {bad}")
        _log(
            f"framework OK: cast={len(fw.cast)} stages={len(fw.stages)} "
            f"involved={fw.involved_ids}"
        )
        _log(f"  note: {fw.casting_note[:200]}")

    vol = deps.outline.read_volume(1)
    if vol is None:
        errors.append("缺少卷大纲")
    else:
        if len(vol.arc) < 400:
            errors.append(f"arc 过短: {len(vol.arc)} 字（期望详尽大纲）")
        if not vol.ending.strip():
            errors.append("ending 为空")
        _log(f"volume OK: 《{vol.title}》 arc={len(vol.arc)} ending={len(vol.ending)}")

    beats = deps.outline.load_volume_beats(1)
    if beats is None or not beats.raw_beats:
        errors.append("缺少 beats")
    else:
        _log(f"beats OK: raw={len(beats.raw_beats)} step={beats.step} chapters_map={len(beats.chapter_map)}")
        if beats.step < 5:
            errors.append(f"beats.step 应为 5，实际 {beats.step}")

    chapters = [c for c in deps.outline.list_chapters() if c.volume == 1]
    if not chapters:
        errors.append("未生成章节")
    else:
        with_scenes = sum(1 for c in chapters if any(b.scenes for b in c.beats))
        _log(f"chapters OK: {len(chapters)} 章, {with_scenes} 章含细场景")
        for c in chapters[:3]:
            _log(f"  ch{c.number}《{c.title}》 beats={len(c.beats)} keynote={c.keynote[:2]}")

    # Trace files
    traces_dir = PROJECT / "traces"
    if traces_dir.exists():
        stages = sorted({p.name for p in traces_dir.rglob("*.json")})
        _log(f"traces: {len(list(traces_dir.rglob('*.json')))} files")
        # show recent stage names from paths
        stage_hints = sorted({
            p.parent.name for p in traces_dir.rglob("*.json")
        })[:20]
        _log(f"  trace folders sample: {stage_hints}")
        wanted = {"volume_framework", "volume_v2", "volume_cast", "volume_beats"}
        found_text = " ".join(str(p) for p in traces_dir.rglob("*"))
        missing_stages = [s for s in wanted if s not in found_text]
        if missing_stages:
            _log(f"  warn: missing trace stage names: {missing_stages}")
        else:
            _log("  trace stages include framework/outline/cast/beats")

    if errors:
        raise AssertionError("验证失败:\n- " + "\n- ".join(errors))


def main() -> int:
    _log("=== reset project ===")
    paths = reset_project()
    _log(f"project: {PROJECT}")

    _log("=== seed planning codex + synopsis ===")
    seed_codex(paths)
    deps = Deps(PROJECT)
    seed_synopsis(deps)
    n_entries = len(PlanningEntityStore(paths).list_entries())
    _log(f"seeded entries: {n_entries}")

    _log("=== plan_volume_v2 ===")
    try:
        run_volume(deps)
    except Exception as exc:
        _log(f"FATAL during plan_volume_v2: {exc!r}")
        raise

    _log("=== verify ===")
    verify(deps)
    _log("=== E2E SUCCESS ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _log(f"=== E2E FAILED: {exc} ===")
        raise
