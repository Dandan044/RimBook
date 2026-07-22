"""Dual-codex migration, foundation, volume steps, and writer boundary tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import yaml

from rimbook.codex.models import CodexEntry
from rimbook.codex.store import CodexStore
from rimbook.llm.prompts import Prompts
from rimbook.outline.store import OutlineStore
from rimbook.pipeline.planner import Planner
from rimbook.planning_entities import (
    PlanningCodexEntry,
    PlanningCodexService,
    PlanningEntityStore,
    PlanningRelationship,
)
from rimbook.project import scaffold_project


class FakeLLM:
    default_model = "fake-model"

    def __init__(self, *, text: str = "", json_responses: list[dict[str, Any]] | None = None) -> None:
        self._text = text
        self._json = list(json_responses or [])
        self.calls: list[list[dict[str, str]]] = []

    def as_chat(
        self,
        system: str,
        user: str | None = None,
        history: Iterable[dict[str, str]] = (),
    ) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": system}, *history]
        if user is not None:
            messages.append({"role": "user", "content": user})
        return messages

    def generate(self, messages: list[dict[str, str]], **_: Any) -> Any:
        self.calls.append(messages)

        class R:
            content = self._text
            usage = None
            model = "fake"
            finish_reason = "stop"

        return R()

    def generate_json(self, messages: list[dict[str, str]], **_: Any) -> dict[str, Any]:
        self.calls.append(messages)
        return self._json.pop(0)


def _detail(label: str, **patch: str) -> dict[str, Any]:
    paragraphs = [
        f"## {label}的起源\n" + f"{label}最初源于一次被长期忽略的选择。" * 20,
        "## 演变与因果\n" + "此后的制度、环境与个人选择彼此推动，留下可追溯的因果链。" * 20,
        "## 留存影响\n" + "这些历史并未消失，而是持续影响当下人物的判断与关系。" * 20,
    ]
    return {"detail": "\n\n".join(paragraphs), "details_patch": patch}


def test_legacy_entities_yaml_migrates_to_planning_codex(tmp_path):
    paths = scaffold_project(tmp_path / "legacy", exist_ok=True)
    legacy = {
        "version": 1,
        "entities": [{
            "id": "hero",
            "name": "林默",
            "surface_goal": "查案",
            "secret": "他其实知情",
            "field_locks": ["secret"],
        }],
        "relationships": [],
        "updated_at": "",
    }
    paths.planning_entities_file.write_text(
        yaml.dump(legacy, allow_unicode=True), encoding="utf-8",
    )

    store = PlanningEntityStore(paths)
    entry = store.get_entry("hero")
    assert entry.type == "character"
    assert entry.secret_truth == "他其实知情"
    assert "secret_truth" in entry.field_locks
    assert store.file_for("character", "hero").exists()
    assert paths.planning_entities_file.exists()  # original preserved


def test_six_type_entries_and_cross_type_relationships(tmp_path):
    paths = scaffold_project(tmp_path / "six", exist_ok=True)
    store = PlanningEntityStore(paths)
    service = PlanningCodexService(store)

    store.save_entry(PlanningCodexEntry(
        id="char_hero", name="林默", type="character", secret_truth="秘密",
    ))
    store.save_entry(PlanningCodexEntry(
        id="loc_city", name="旧城", type="location",
        details={"strategic_value": "交通枢纽"},
    ))
    store.save_relationship(
        PlanningRelationship(
            id="hero-city",
            source_id="char_hero",
            target_id="loc_city",
            relationship_type="lives_in",
            conflict="被人监视",
        )
    )
    brief = service.render_brief(["char_hero", "loc_city"])
    assert "林默" in brief and "旧城" in brief and "被人监视" in brief


def test_foundation_isolates_bad_entries(tmp_path):
    paths = scaffold_project(tmp_path / "foundation", exist_ok=True)
    outline = OutlineStore(paths)
    service = PlanningCodexService(PlanningEntityStore(paths))
    llm = FakeLLM(
        text="宏观梗概：主题是真相。",
        json_responses=[
            {
                "entries": [
                    {
                        "id": "hero", "name": "林默", "type": "character",
                        "secret_truth": "知情", "exists_at_anchor": True,
                        "existence_reason": "故事开篇已经成年",
                    },
                    "not-an-object",
                    {"name": "缺少id", "exists_at_anchor": True},
                    {
                        "id": "loc_a", "name": "旧城", "type": "location",
                        "exists_at_anchor": True,
                        "existence_reason": "已有百年历史",
                    },
                ],
                "relationships": [
                    {"id": "r1", "source_id": "hero", "target_id": "loc_a", "conflict": "逃离"},
                ],
            },
            _detail("旧城", strategic_value="交通枢纽"),
            _detail("林默", inner_need="确认自己没有重蹈父亲覆辙", fear="真相证明自己也是共犯"),
        ],
    )
    planner = Planner(llm, Prompts(), outline, planning_entities=service)
    events = list(planner.plan_foundation("一个旧案重开的故事"))
    assert outline.read_synopsis().startswith("宏观梗概")
    assert {e.id for e in service.store.list_entries()} == {"hero", "loc_a"}
    assert service.store.list_relationships()[0].id == "r1"
    done_steps = [
        e["data"]["step"] for e in events
        if e["event"] == "step" and e["data"].get("status") == "done"
    ]
    assert done_steps == list(range(1, 9))
    assert service.store.get_entry("hero").details["inner_need"]
    assert service.store.get_entry("loc_a").detail.startswith("## 旧城")
    # Character detail is generated after location and sees its completed history.
    assert "旧城最初源于" in llm.calls[3][-1]["content"]


def test_future_existence_becomes_timeline_event(tmp_path):
    paths = scaffold_project(tmp_path / "existence", exist_ok=True)
    service = PlanningCodexService(PlanningEntityStore(paths))
    result = service.apply_foundation_entries(
        [
            {
                "id": "loc_city", "name": "A市", "type": "location",
                "exists_at_anchor": True,
                "existence_reason": "故事开始前已建成",
            },
            {
                "id": "faction_survivor_settlement",
                "name": "幸存者聚落",
                "type": "faction",
                "exists_at_anchor": False,
                "existence_reason": "主角未来才会组织成立",
                "formation_event": {
                    "id": "evt_survivor_settlement_formed",
                    "name": "幸存者聚落成立",
                    "description": "主角联合三支幸存者队伍建立共同议事与防卫制度。",
                },
            },
            {
                "id": "evt_second_future", "name": "另一项未来成立事件", "type": "timeline",
                "exists_at_anchor": False,
                "surface_summary": "另一项未来事件尚未发生，但其条件已进入规划。",
            },
        ],
        source="foundation",
        require_existence=True,
    )
    ids = {entry.id for entry in service.store.list_entries()}
    assert "loc_city" in ids
    assert "faction_survivor_settlement" not in ids
    assert "evt_survivor_settlement_formed" in ids
    assert "evt_second_future" in ids
    assert service.store.get_entry("evt_second_future").details["event_status"] == "planned"
    assert any("尚未存在" in warning for warning in result.warnings)
    issues = service.detail_quality_issues(
        "loc_city",
        ("## 历史\nA市已有两百年历史。\n\n## 组织\n"
         "主角与同伴共同建立幸存者聚落，此后它成为新的权力中心。" * 20),
    )
    assert any("既成事实" in issue for issue in issues)
    planned_issues = service.detail_quality_issues(
        "evt_second_future",
        ("## 结果\n该事件已经完成，所有成立条件已满足。\n\n"
         "## 余波\n新的组织开始运行。" * 20),
    )
    assert any("planned 时间线" in issue for issue in planned_issues)


def test_volume_steps_are_one_to_four_and_cast_visible(tmp_path):
    paths = scaffold_project(tmp_path / "vol", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("梗概")
    service = PlanningCodexService(PlanningEntityStore(paths))

    def beat(i: int) -> dict[str, Any]:
        return {
            "id": f"b{i:02d}", "goal": f"g{i}", "conflict": f"c{i}",
            "outcome": f"o{i}", "entities": ["hero"], "momentum": "m",
        }

    beats = [beat(i) for i in range(1, 13)]
    chapters = [{
        "title": f"章{i}", "beat_ids": [b["id"] for b in beats[(i - 1) * 4:i * 4]],
        "purpose": "p", "value_shift": "a→b", "tension": i,
        "hook": "h", "story_date": "d", "elapsed": "e",
        "keynote": ["k"], "bridge_beats": [],
    } for i in range(1, 4)]
    micros = [{"beats": [{**b, "scenes": []} for b in beats[i:i + 4]]} for i in range(0, 12, 4)]

    llm = FakeLLM(json_responses=[
        {"title": "卷一", "arc": "弧", "ending": "收束", "chapter_count": 3},
        {
            "entries": [{
                "id": "hero", "name": "林默", "type": "character",
                "secret_truth": "知情", "exists_at_anchor": True,
                "existence_reason": "已在故事开篇出现",
            }],
            "relationships": [],
        },
        {"beats": beats},
        {"chapters": chapters},
        *micros,
    ])
    planner = Planner(llm, Prompts(), outline, planning_entities=service)
    events = [e for e in planner.plan_volume_v2(1) if e["event"] == "step"]
    steps = [e["data"]["step"] for e in events if e["data"].get("status") == "done"]
    assert steps == [1, 2, 3, 4]
    assert "林默" in llm.calls[2][-1]["content"]  # beat prompt sees cast
    assert service.store.get_entry("hero").secret_truth == "知情"


def test_detail_failure_isolated_and_retry_targets_missing_only(tmp_path):
    paths = scaffold_project(tmp_path / "detail-retry", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("两名调查者追查一座旧城的历史。")
    service = PlanningCodexService(PlanningEntityStore(paths))
    service.store.save_entry(PlanningCodexEntry(
        id="char_a", name="甲", type="character",
    ))
    service.store.save_entry(PlanningCodexEntry(
        id="char_b", name="乙", type="character",
    ))
    llm = FakeLLM(json_responses=[
        {"detail": "过短", "details_patch": {}},
        {"detail": "仍然过短", "details_patch": {}},
        _detail("乙", voice="说话谨慎"),
        _detail("甲", fear="害怕历史重演"),
    ])
    planner = Planner(llm, Prompts(), outline, planning_entities=service)

    first_events = list(planner.generate_codex_details(only_missing=True))
    character_done = next(
        event for event in first_events
        if event["event"] == "step"
        and event["data"].get("entry_type") == "character"
        and event["data"].get("status") == "done"
    )
    assert character_done["data"]["completed"] == 1
    assert character_done["data"]["skipped"] == 1
    first_details = {
        entry.id: entry.detail
        for entry in service.store.list_entries("character")
    }
    assert sum(bool(detail) for detail in first_details.values()) == 1
    missing_id = next(entry_id for entry_id, detail in first_details.items() if not detail)

    list(planner.generate_codex_details(only_missing=True))
    assert service.store.get_entry(missing_id).detail
    assert len(llm.calls) == 4  # completed character was not regenerated


def test_assembler_does_not_load_planning_secrets(tmp_path):
    """Writer-facing assembler must never import or read planning codex secrets."""
    import inspect
    import rimbook.memory.assembler as assembler_mod

    source = inspect.getsource(assembler_mod)
    assert "planning_entities" not in source
    assert "planning/codex" not in source
    assert "secret_truth" not in source

    paths = scaffold_project(tmp_path / "boundary", exist_ok=True)
    store = PlanningEntityStore(paths)
    store.save_entry(PlanningCodexEntry(
        id="hero", name="林默", type="character",
        secret_truth="绝对不能泄露的幕后真相XYZ",
    ))
    # Revealed codex remains independent
    codex = CodexStore(paths)
    codex.write(CodexEntry(
        id="hero", name="林默", type="character",
        body="读者已知：他是侦探。",
    ))
    revealed = codex.read("hero")
    assert "绝对不能泄露" not in revealed.body
    assert "读者已知" in revealed.body
