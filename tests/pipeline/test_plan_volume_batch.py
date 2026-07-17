"""Integration tests for Planner.plan_volume batch planning (fake LLM)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from rimbook.llm.prompts import Prompts
from rimbook.outline.models import VolumeOutline
from rimbook.outline.store import OutlineStore
from rimbook.pipeline.planner import Planner
from rimbook.project import scaffold_project


class FakeLLM:
    """Minimal LLM stand-in: as_chat + sequenced generate_json responses."""

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
    ) -> dict[str, Any]:
        self.calls.append(list(messages))
        if not self._json_responses:
            raise RuntimeError("FakeLLM: no more generate_json responses")
        return self._json_responses.pop(0)


def _chapter_payload(title: str) -> dict[str, Any]:
    return {
        "title": title,
        "entities": ["char_hero"],
        "tags": ["主线"],
        "notes": "",
        "purpose": "推进主线",
        "value_shift": "平静→紧张",
        "tension": 3,
        "hook": "留下悬念",
        "story_date": "第1日",
        "elapsed": "半日",
        "beats": [
            {
                "goal": "发现线索",
                "conflict": "有人阻拦",
                "outcome": "拿到线索",
                "entities": ["char_hero"],
            }
        ],
    }


def _volume_turn1(**overrides: Any) -> dict[str, Any]:
    data = {
        "title": "雾起之卷",
        "arc": "主角卷入旧案，冲突逐步升级。",
        "ending": "旧案真相初现，留下下卷钩子。",
        "chapter_count": 3,
    }
    data.update(overrides)
    return data


def _chapters_turn2(count: int = 3) -> dict[str, Any]:
    return {
        "chapters": [_chapter_payload(f"第{i}章") for i in range(1, count + 1)]
    }


def _planner(tmp_path, llm: FakeLLM) -> Planner:
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    outline = OutlineStore(paths)
    outline.write_synopsis("全书梗概：一场旧案重开。")
    return Planner(llm=llm, prompts=Prompts(), outline=outline)


def test_plan_volume_happy_path_persists(tmp_path):
    llm = FakeLLM([_volume_turn1(), _chapters_turn2(3)])
    planner = _planner(tmp_path, llm)

    result = planner.plan_volume(1, title="用户标题")

    assert result.volume.number == 1
    assert result.volume.title == "用户标题"
    assert result.volume.ending.strip()
    assert result.volume.chapters == [1, 2, 3]
    assert len(result.chapters) == 3

    stored = planner.outline.read_volume(1)
    assert stored is not None
    assert stored.ending.startswith("旧案真相")
    assert stored.chapters == [1, 2, 3]

    for i, ch in enumerate(result.chapters, start=1):
        assert ch.number == i
        assert ch.volume == 1
        assert ch.beats
        disk = planner.outline.read_chapter(i)
        assert disk is not None
        assert disk.volume == 1
        assert disk.beats


def test_plan_volume_duplicate_raises(tmp_path):
    llm = FakeLLM([_volume_turn1(), _chapters_turn2(3)])
    planner = _planner(tmp_path, llm)
    planner.outline.write_volume(
        VolumeOutline(number=1, title="已有", arc="arc", ending="end")
    )

    with pytest.raises(FileExistsError, match="已存在"):
        planner.plan_volume(1)


def test_plan_chapter_detailed_requires_volume(tmp_path):
    llm = FakeLLM([])
    planner = _planner(tmp_path, llm)

    with pytest.raises(ValueError, match="必须指定所属卷"):
        planner.plan_chapter_detailed(1, volume=None)


def test_plan_volume_second_turn_includes_assistant_history(tmp_path):
    turn1 = _volume_turn1()
    llm = FakeLLM([turn1, _chapters_turn2(3)])
    planner = _planner(tmp_path, llm)

    planner.plan_volume(1)

    assert len(llm.calls) == 2
    second_msgs = llm.calls[1]
    assistant_msgs = [m for m in second_msgs if m["role"] == "assistant"]
    assert assistant_msgs
    assert "旧案真相初现" in assistant_msgs[0]["content"]
    assert "ending" in assistant_msgs[0]["content"]
