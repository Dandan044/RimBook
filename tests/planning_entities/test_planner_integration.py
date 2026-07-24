from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rimbook.llm.prompts import Prompts
from rimbook.outline.store import OutlineStore
from rimbook.pipeline.planner import Planner
from rimbook.planning_entities import (
    EntityNetworkService,
    PlanningCodexEntry,
    PlanningEntityStore,
)
from rimbook.project import scaffold_project


class FakeLLM:
    default_model = "fake-model"

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

    def generate_json(self, messages: list[dict[str, str]], **_: Any) -> dict[str, Any]:
        self.calls.append(messages)
        return self.responses.pop(0)


def _beat(number: int) -> dict[str, Any]:
    return {
        "id": f"b{number:02d}",
        "goal": f"目标{number}",
        "conflict": f"冲突{number}",
        "outcome": f"结果{number}",
        "entities": ["hero", "mentor"],
        "momentum": "局势收紧",
    }


def _framework() -> dict[str, Any]:
    return {
        "reader_lens": {
            "current_perspective": "读者跟随林默查案",
            "what_they_want": "想知道周岚隐瞒了什么",
            "reveal_debts": ["周岚的秘密"],
        },
        "craft_focus": {
            "conflict": "证据归属冲突",
            "reversal": "半份档案",
            "development": "信任裂痕",
            "suspense": "信息差",
            "other": "",
        },
        "stages": [],
        "cast": [
            {
                "id": "hero",
                "billing": "lead",
                "situation": "林默必须查清旧案",
                "dramatic_impact": "推动真相逼近",
            },
            {
                "id": "mentor",
                "billing": "supporting",
                "situation": "周岚持有秘密",
                "dramatic_impact": "制造信任危机",
            },
        ],
        "casting_note": "旧案双人对照",
        "involved_ids": ["hero", "mentor"],
    }


def test_volume_v2_cast_expansion_before_beats(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("林默必须查清旧案，并决定是否相信带着秘密的周岚。")
    service = EntityNetworkService(PlanningEntityStore(paths))
    # Seed so framework can reference known ids
    service.store.save_entry(PlanningCodexEntry(
        id="hero", name="林默", type="character",
        surface_summary="查案者", narrative_role="主角", reveal_strategy="开篇",
    ))
    service.store.save_entry(PlanningCodexEntry(
        id="mentor", name="周岚", type="character",
        surface_summary="知情者", narrative_role="秘密持有人", reveal_strategy="侧写",
    ))
    beats = [_beat(i) for i in range(1, 13)]
    chapters = [
        {
            "title": f"第{index}章",
            "beat_ids": [beat["id"] for beat in beats[(index - 1) * 4:index * 4]],
            "purpose": "推进冲突",
            "value_shift": "信任→怀疑",
            "tension": index,
            "hook": "新证据",
            "story_date": f"第{index}日",
            "elapsed": "半日",
            "keynote": ["秘密不明说"],
            "bridge_beats": [],
        }
        for index in range(1, 4)
    ]
    micros = [{"beats": [{**beat, "scenes": []} for beat in beats[i:i + 4]]} for i in range(0, 12, 4)]
    llm = FakeLLM([
        _framework(),
        {
            "title": "旧案卷",
            "arc": "林默发现证据被周岚隐瞒。" * 30,
            "ending": "周岚交出半份档案。",
            "chapter_count": 3,
        },
        {
            "entries": [
                {
                    "id": "hero", "name": "林默", "type": "character",
                    "surface_summary": "查清旧案",
                    "narrative_role": "主角",
                    "reveal_strategy": "开篇",
                    "exists_at_anchor": True,
                    "existence_reason": "本卷开始前已经存在",
                },
                {
                    "id": "mentor", "name": "周岚", "type": "character",
                    "surface_summary": "知情者",
                    "narrative_role": "秘密持有人",
                    "reveal_strategy": "侧写",
                    "exists_at_anchor": True,
                    "existence_reason": "本卷开始前已在旧案中任职",
                },
            ],
            "relationships": [{
                "id": "hero-mentor",
                "source_id": "hero",
                "target_id": "mentor",
                "relationship_type": "allies",
                "conflict": "是否交出真相",
            }],
        },
        {"beats": beats},
        {"chapters": chapters},
        *micros,
    ])
    planner = Planner(llm, Prompts(), outline, planning_entities=service)

    events = list(planner.plan_volume_v2(1))

    assert events[0]["data"]["step"] == 1
    step3_done = next(
        e for e in events
        if e["event"] == "step"
        and e["data"].get("step") == 3
        and e["data"].get("status") == "done"
    )
    assert "设定扩充" in step3_done["data"]["message"] or "变更" in step3_done["data"]["message"]
    # calls: 0 framework, 1 outline, 2 cast, 3 beats — beats sees cast entities
    assert "林默" in llm.calls[3][-1]["content"]
    network = service.store.read_network()
    assert {entity.id for entity in network.entities} == {"hero", "mentor"}
    assert network.relationships[0].conflict == "是否交出真相"
    assert outline.load_volume_framework(1) is not None
