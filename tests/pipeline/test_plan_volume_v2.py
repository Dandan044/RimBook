"""Tests for Planner.plan_volume_v2 with framework → outline → MicroScene."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rimbook.llm.prompts import Prompts
from rimbook.outline.store import OutlineStore
from rimbook.pipeline.planner import Planner, _parse_volume_framework
from rimbook.project import scaffold_project


class FakeLLM:
    def __init__(self, json_responses: list[dict[str, Any]]) -> None:
        self._json_responses = list(json_responses)
        self.calls: list[list[dict[str, str]]] = []
        self.default_model = "fake-model"

    def as_chat(
        self,
        system: str,
        user: str | None = None,
        history: Iterable[dict[str, str]] = (),
    ) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
        msgs.extend(history)
        if user is not None:
            msgs.append({"role": "user", "content": user})
        return msgs

    def generate_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append(list(messages))
        if not self._json_responses:
            raise RuntimeError("FakeLLM: no more generate_json responses")
        return self._json_responses.pop(0)


def _raw_beat(i: int) -> dict[str, Any]:
    return {
        "id": f"b{i:02d}",
        "goal": f"目标{i}",
        "conflict": f"冲突{i}",
        "outcome": f"结果{i}",
        "entities": ["char_hero"],
        "momentum": f"动量{i}",
    }


def _micro_scenes() -> list[dict[str, Any]]:
    return [
        {
            "intent": "走廊湿冷压迫感压垮侥幸",
            "sensory": "霉味、滴水回声",
            "action": "",
            "dialogue": "",
            "event": "",
            "technique": "环境隐喻",
            "pacing": "缓起",
            "words": 280,
        },
        {
            "intent": "确认吊坠在回应危险",
            "sensory": "掌心温度异常",
            "action": "握住吊坠",
            "dialogue": "",
            "event": "温度异常",
            "technique": "触感描写",
            "pacing": "加速",
            "words": 220,
        },
    ]


def _framework() -> dict[str, Any]:
    return {
        "reader_lens": {
            "current_perspective": "读者刚开书，只知旧案重开。",
            "what_they_want": "想看主角如何被卷入。",
            "reveal_debts": ["病毒真相尚未对读者揭露"],
        },
        "craft_focus": {
            "conflict": "外部调查压迫",
            "reversal": "吊坠异常",
            "development": "侥幸到恐惧",
            "suspense": "信息差",
            "other": "近距离第三人称",
        },
        "stages": [],
        "cast": [
            {
                "id": "char_hero",
                "billing": "lead",
                "situation": "主角在雾城边缘苏醒，旧案阴影未散。",
                "dramatic_impact": "将被迫面对调查并推动悬念。",
            }
        ],
        "casting_note": "本卷聚焦卷入旧案",
        "involved_ids": ["char_hero"],
    }


def _planner(tmp_path, llm: FakeLLM) -> Planner:
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("全书梗概：一场旧案重开。")
    return Planner(llm=llm, prompts=Prompts(), outline=outline)


def test_plan_volume_v2_keynote_and_microscenes(tmp_path):
    n_beats = 6
    chapter_count = 2

    framework = _framework()
    turn_outline = {
        "title": "雾起之卷",
        "arc": "主角卷入旧案。" * 40,
        "ending": "真相初现。",
        "chapter_count": chapter_count,
    }
    turn_beats = {"beats": [_raw_beat(i) for i in range(1, n_beats + 1)]}

    assemble = {
        "chapters": [
            {
                "title": "第一章",
                "beat_ids": ["b01", "b02", "b03"],
                "purpose": "开场",
                "value_shift": "平静→不安",
                "tension": 2,
                "hook": "吊坠发热",
                "story_date": "第1日",
                "elapsed": "半日",
                "keynote": [
                    "近距离第三人称跟林默",
                    "林默不知道病毒真相",
                    "结尾禁止总结世界改变了",
                ],
                "bridge_beats": [],
            },
            {
                "title": "第二章",
                "beat_ids": ["b04", "b05", "b06"],
                "purpose": "推进",
                "value_shift": "不安→恐惧",
                "tension": 4,
                "hook": "门外脚步",
                "story_date": "第1日夜",
                "elapsed": "数时",
                "keynote": ["感染变化只通过触感表现"],
                "bridge_beats": [],
            },
        ]
    }

    micro1 = {
        "beats": [
            {**_raw_beat(i), "scenes": _micro_scenes()}
            for i in range(1, 4)
        ]
    }
    micro2 = {
        "beats": [
            {**_raw_beat(i), "scenes": _micro_scenes()}
            for i in range(4, 7)
        ]
    }

    # framework, outline, beats, assemble, micro×2 (no planning_entities → skip cast LLM)
    llm = FakeLLM([framework, turn_outline, turn_beats, assemble, micro1, micro2])
    planner = _planner(tmp_path, llm)

    events = list(planner.plan_volume_v2(1))
    assert any(
        e["data"].get("step") == 5 and e["data"].get("status") == "done"
        for e in events if e["event"] == "step"
    )
    assert any(
        e["data"].get("step") == 1 and e["data"].get("status") == "done"
        for e in events if e["event"] == "step"
    )

    fw = planner.outline.load_volume_framework(1)
    assert fw is not None
    assert fw.cast[0].id == "char_hero"
    assert "卷入旧案" in fw.casting_note

    assert len(llm.calls) == 6
    assert "叙事设计师" in llm.calls[0][0]["content"]

    ch1 = planner.outline.read_chapter(1)
    assert ch1 is not None
    assert ch1.keynote[0].startswith("近距离")
    assert len(ch1.beats) == 3
    assert len(ch1.beats[0].scenes) == 2
    assert ch1.beats[0].scenes[0].technique == "环境隐喻"
    assert ch1.beats[0].scenes[0].intent.startswith("走廊")
    assert ch1.beats[0].scenes[0].action == ""
    assert ch1.beats[0].scenes[0].sensory
    assert "手法：" not in (ch1.notes or "")

    beat_data = planner.outline.load_volume_beats(1)
    assert beat_data is not None
    assert beat_data.step == 5
    assert beat_data.chapter_map[0].keynote


def test_microscene_fallback_on_parse_error(tmp_path):
    framework = _framework()
    turn_outline = {"title": "卷", "arc": "a", "ending": "e", "chapter_count": 1}
    turn_beats = {"beats": [_raw_beat(i) for i in range(1, 4)]}
    assemble = {
        "chapters": [{
            "title": "一",
            "beat_ids": ["b01", "b02", "b03"],
            "purpose": "p", "value_shift": "a→b", "tension": 2,
            "hook": "h", "story_date": "d", "elapsed": "e",
            "keynote": ["视角：主角"],
            "bridge_beats": [],
        }]
    }

    class Flaky(FakeLLM):
        def generate_json(self, messages, **kw):
            self.calls.append(list(messages))
            # 5th call = microscene → fail
            if len(self.calls) == 5:
                raise ValueError("无法解析 JSON")
            return self._json_responses.pop(0)

    llm = Flaky([framework, turn_outline, turn_beats, assemble])
    planner = _planner(tmp_path, llm)
    list(planner.plan_volume_v2(1))
    ch = planner.outline.read_chapter(1)
    assert ch is not None
    assert ch.keynote == ["视角：主角"]
    assert len(ch.beats) == 3
    assert ch.beats[0].scenes == []


def test_legacy_microscene_intent_backfill(tmp_path):
    """Old scenes without intent should backfill from event/action on read."""
    paths = scaffold_project(tmp_path / "legacy", exist_ok=True)
    outline = OutlineStore(paths)
    ch_path = paths.chapter_outline(1)
    ch_path.parent.mkdir(parents=True, exist_ok=True)
    ch_path.write_text(
        "---\n"
        "number: 1\n"
        "title: 旧章\n"
        "volume: 1\n"
        "beats:\n"
        "  - goal: g\n"
        "    conflict: c\n"
        "    outcome: o\n"
        "    entities: []\n"
        "    scenes:\n"
        "      - action: 推开门\n"
        "        dialogue: ''\n"
        "        event: 发现异常\n"
        "        technique: 环境隐喻\n"
        "        pacing: 缓起\n"
        "        words: 200\n"
        "keynote: []\n"
        "---\n",
        encoding="utf-8",
    )
    ch = outline.read_chapter(1)
    assert ch is not None
    assert ch.beats[0].scenes[0].intent == "发现异常"
    assert ch.beats[0].scenes[0].action == "推开门"
    assert ch.beats[0].scenes[0].sensory == ""


def test_parse_framework_drops_unknown_ids_and_outline_fields():
    raw = {
        "title": "应被忽略",
        "arc": "也应忽略",
        "reader_lens": {
            "current_perspective": "p",
            "what_they_want": "w",
            "reveal_debts": [],
        },
        "craft_focus": {},
        "stages": [
            {"id": "loc_gate", "why_this_stage": "主舞台", "dramatic_pressure": "压迫"},
        ],
        "cast": [
            {
                "id": "char_hero",
                "billing": "lead",
                "situation": "s",
                "dramatic_impact": "i",
            },
            {
                "id": "char_ghost",
                "billing": "cameo",
                "situation": "x",
                "dramatic_impact": "y",
            },
        ],
        "casting_note": "note",
        "involved_ids": ["char_hero", "loc_gate", "char_ghost"],
    }
    fw, warnings = _parse_volume_framework(
        raw, volume_number=1, known_ids={"char_hero", "loc_gate"},
    )
    assert fw.cast[0].id == "char_hero"
    assert all(c.id != "char_ghost" for c in fw.cast)
    assert "char_ghost" not in fw.involved_ids
    assert any("禁止字段" in w for w in warnings)
    assert any("未知" in w for w in warnings)
