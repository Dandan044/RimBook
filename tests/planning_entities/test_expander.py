from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rimbook.llm.prompts import Prompts
from rimbook.outline.store import OutlineStore
from rimbook.pipeline.planner import Planner
from rimbook.planning_entities import (
    ExpansionBudget,
    ExpansionCandidate,
    PlanningCodexEntry,
    PlanningCodexService,
    PlanningEntityStore,
    WorldExpander,
)
from rimbook.project import scaffold_project


def _expander(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    service = PlanningCodexService(PlanningEntityStore(paths))
    return service, WorldExpander(service)


def test_coefficient_one_preserves_current_world_scale():
    budget = ExpansionBudget.for_coefficient(1)
    assert budget.max_depth == 0
    assert budget.max_new_per_run == 0
    assert budget.max_llm_calls == 0


def test_budget_presets_increase_but_remain_hard_capped():
    b2 = ExpansionBudget.for_coefficient(2)
    b3 = ExpansionBudget.for_coefficient(3)
    b4 = ExpansionBudget.for_coefficient(4)
    assert (b2.max_depth, b2.max_new_per_run) == (1, 12)
    assert b2.max_new_per_run < b3.max_new_per_run < b4.max_new_per_run
    assert b4.max_new_per_run == 55


def test_dedup_matches_same_type_name_and_alias(tmp_path):
    service, expander = _expander(tmp_path)
    service.store.save_entry(PlanningCodexEntry(
        id="faction_bright",
        name="明光幸存者",
        type="faction",
        aliases=["明光队"],
    ))
    candidates = [
        ExpansionCandidate(
            provisional_id="faction_duplicate",
            name="明光队",
            type="faction",
            source_entry_ids=["world_disaster"],
            relatedness=0.9,
        ),
        ExpansionCandidate(
            provisional_id="char_zhang",
            name="张建军",
            type="character",
            source_entry_ids=["faction_bright"],
            relatedness=0.9,
        ),
    ]

    accepted, warnings = expander.deduplicate(candidates)
    assert not warnings
    assert accepted[0].existing_match_id == "faction_bright"
    assert accepted[1].existing_match_id == ""


def test_selection_respects_global_and_per_seed_limits(tmp_path):
    service, expander = _expander(tmp_path)
    state = expander.start_or_resume(coefficient=2, seed_ids=["faction_a"])
    budget = ExpansionBudget.for_coefficient(2)
    candidates = [
        ExpansionCandidate(
            provisional_id=f"char_{index}",
            name=f"关键人物{index}",
            type="character",
            source_entry_ids=["faction_a"],
            relatedness=0.95 - index * 0.01,
        )
        for index in range(8)
    ]
    selected = expander.select(candidates, budget=budget, state=state)
    assert len(selected) == budget.max_new_per_seed == 2


def test_materialize_creates_source_relation_and_audit_metadata(tmp_path):
    service, expander = _expander(tmp_path)
    service.store.save_entry(PlanningCodexEntry(
        id="faction_council",
        name="铁壁堡垒议会",
        type="faction",
        detail="议会由创始人与若干关键成员构成。",
    ))
    state = expander.start_or_resume(
        coefficient=2,
        seed_ids=["faction_council"],
    )
    candidate = ExpansionCandidate(
        provisional_id="char_zhang_jianjun",
        name="张建军",
        type="character",
        source_entry_ids=["faction_council"],
        evidence="铁壁堡垒议会创始人张建军决定开放东门。",
        importance="创始人兼议会关键票",
        relationship_type="founded",
        relatedness=0.96,
        exists_at_anchor=True,
        existence_reason="议会成立时已担任创始人",
        surface_summary="铁壁堡垒议会创始人。",
    )

    created, result = expander.materialize(
        [candidate],
        depth=1,
        state=state,
    )
    assert created == ["char_zhang_jianjun"]
    entry = service.store.get_entry("char_zhang_jianjun")
    assert entry.details["expansion_depth"] == 1
    assert entry.details["source_entry_ids"] == ["faction_council"]
    relation = service.store.list_relationships()[0]
    assert relation.source_id == "faction_council"
    assert relation.target_id == "char_zhang_jianjun"
    assert result.created_relationships


class FakeLLM:
    default_model = "fake"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
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

    def generate_json(self, messages, **_):
        self.calls.append(messages)
        return self.responses.pop(0)


def _long_detail(name: str) -> dict[str, Any]:
    return {
        "detail": (
            f"## {name}的生平\n"
            + "他在堡垒形成前经历了长期迁徙，这些经历塑造了他的决策方式。" * 20
            + "\n\n## 议会时期\n"
            + "他用工程经验建立制度，同时承担每一次错误决策的代价。" * 20
        ),
        "details_patch": {
            "inner_need": "让堡垒制度能够保护普通人",
            "fear": "自己的权威变成另一种暴政",
            "voice": "简短、命令式，但会解释数字依据",
        },
    }


def test_planner_expands_one_depth_and_generates_detail(tmp_path):
    paths = scaffold_project(tmp_path / "planner", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("灾后堡垒围绕资源分配发生冲突。")
    service = PlanningCodexService(PlanningEntityStore(paths))
    service.store.save_entry(PlanningCodexEntry(
        id="faction_wall",
        name="铁壁堡垒议会",
        type="faction",
        detail="议会有九名成员。创始人张建军掌握决定性一票，并反对永久封锁东门。",
        narrative_role="堡垒的权力中心",
    ))
    llm = FakeLLM([
        {
            "candidates": [{
                "provisional_id": "char_zhang_jianjun",
                "name": "张建军",
                "type": "character",
                "source_entry_ids": ["faction_wall"],
                "evidence": "创始人张建军掌握决定性一票",
                "importance": "创始人兼制度冲突核心",
                "relationship_type": "founded",
                "relatedness": 0.95,
                "exists_at_anchor": True,
                "existence_reason": "堡垒议会成立前已经成年",
                "surface_summary": "铁壁堡垒议会创始人。",
                "narrative_role": "制度理想与生存压力的冲突轴",
            }],
        },
        _long_detail("张建军"),
    ])
    planner = Planner(
        llm,
        Prompts(),
        outline,
        planning_entities=service,
    )

    events = list(planner.expand_world(coefficient=2))
    done = next(
        event for event in events
        if event["event"] == "step" and event["data"].get("status") == "done"
    )
    assert done["data"]["depth"] == 1
    assert done["data"]["created_entry_ids"] == ["char_zhang_jianjun"]
    entry = service.store.get_entry("char_zhang_jianjun")
    assert entry.detail.startswith("## 张建军")
    assert entry.details["inner_need"]
    assert service.store.list_relationships()[0].relationship_type == "founded"
    assert len(llm.calls) == 2


def test_materialize_rejects_future_existence_without_formation_event(tmp_path):
    service, expander = _expander(tmp_path)
    service.store.save_entry(PlanningCodexEntry(
        id="faction_council",
        name="铁壁堡垒议会",
        type="faction",
        detail="议会计划在未来建立灯塔聚落。",
    ))
    state = expander.start_or_resume(coefficient=2, seed_ids=["faction_council"])
    future = ExpansionCandidate(
        provisional_id="loc_lighthouse",
        name="灯塔聚落",
        type="location",
        source_entry_ids=["faction_council"],
        relatedness=0.9,
        exists_at_anchor=False,
        existence_reason="尚未建立",
        surface_summary="未来沿海聚落。",
    )
    created, result = expander.materialize([future], depth=1, state=state)
    assert created == []
    assert any("尚未" in warning or "存在" in warning for warning in result.warnings)


def test_coefficient_one_expand_world_is_noop(tmp_path):
    paths = scaffold_project(tmp_path / "noop", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("测试")
    service = PlanningCodexService(PlanningEntityStore(paths))
    service.store.save_entry(PlanningCodexEntry(
        id="faction_wall",
        name="铁壁议会",
        type="faction",
        detail="已有详情。",
    ))
    planner = Planner(
        FakeLLM([]),
        Prompts(),
        outline,
        planning_entities=service,
    )
    events = list(planner.expand_world(coefficient=1))
    assert events == []
    assert len(service.store.list_entries()) == 1


def test_graph_projection_derives_world_edges_without_persisting(tmp_path):
    service, _ = _expander(tmp_path)
    service.store.save_entry(PlanningCodexEntry(
        id="world_rules", name="灾后规则", type="worldbuilding",
    ))
    service.store.save_entry(PlanningCodexEntry(
        id="faction_wall", name="铁壁议会", type="faction",
    ))
    service.store.save_entry(PlanningCodexEntry(
        id="char_zhang", name="张建军", type="character",
    ))
    from rimbook.planning_entities import PlanningRelationship
    service.store.save_relationship(PlanningRelationship(
        id="zhang-wall",
        source_id="char_zhang",
        target_id="faction_wall",
        relationship_type="founded",
    ))

    graph = service.build_graph(include_implicit_world=True)
    assert len(graph["nodes"]) == 3
    assert any(edge["kind"] == "implicit_world" for edge in graph["edges"])
    assert any(edge["id"] == "zhang-wall" for edge in graph["edges"])
    assert len(service.store.list_relationships()) == 1

    focused = service.build_graph(focus="char_zhang", depth=1)
    assert {node["id"] for node in focused["nodes"]} == {
        "char_zhang", "faction_wall",
    }
