from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rimbook.llm.prompts import Prompts
from rimbook.outline.store import OutlineStore
from rimbook.pipeline.planner import Planner
from rimbook.planning_entities import EntityNetworkService, PlanningEntityStore
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


def test_volume_v2_syncs_before_outline_and_reconciles_planned_cast(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("林默必须查清旧案，并决定是否相信带着秘密的周岚。")
    service = EntityNetworkService(PlanningEntityStore(paths))
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
        {"entities": [{"id": "hero", "name": "林默", "surface_goal": "查清旧案"}]},
        {
            "title": "旧案卷",
            "arc": "林默发现证据被周岚隐瞒。",
            "ending": "周岚交出半份档案。",
            "chapter_count": 3,
            "entity_changes": {
                "entities": [{"id": "mentor", "name": "周岚", "story_role": "秘密持有人"}]
            },
        },
        {
            "beats": beats,
            "entity_changes": {
                "relationships": [{
                    "id": "hero-mentor",
                    "source_entity_id": "hero",
                    "target_entity_id": "mentor",
                    "relationship_type": "allies",
                    "conflict": "是否交出真相",
                }]
            },
        },
        {"chapters": chapters},
        *micros,
    ])
    planner = Planner(llm, Prompts(), outline, planning_entities=service)

    events = list(planner.plan_volume_v2(1))

    assert events[0]["data"]["step"] == 0
    assert events[1]["data"]["status"] == "done"
    assert "林默" in llm.calls[1][-1]["content"]  # Step 1 sees the backfilled network.
    assert "周岚" in llm.calls[2][-1]["content"]  # Step 2 sees the cast from Step 1.
    network = service.store.read_network()
    assert {entity.id for entity in network.entities} == {"hero", "mentor"}
    assert network.relationships[0].conflict == "是否交出真相"
