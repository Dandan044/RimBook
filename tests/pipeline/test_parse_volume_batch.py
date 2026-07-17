"""Pure-dict tests for volume + chapters JSON parsers (no LLM)."""

from __future__ import annotations

import pytest

from rimbook.pipeline.planner import _parse_volume_chapters_json, _parse_volume_json


def test_parse_volume_json_happy_path():
    title, arc, ending, chapter_count, warnings = _parse_volume_json(
        {
            "title": "雾起之卷",
            "arc": "主角卷入旧案，冲突逐步升级。",
            "ending": "旧案真相初现，留下下卷钩子。",
            "chapter_count": 5,
        },
        number=1,
        title_hint="",
    )
    assert title == "雾起之卷"
    assert "旧案" in arc
    assert ending.startswith("旧案真相")
    assert chapter_count == 5
    assert warnings == []


def test_parse_volume_json_prefers_title_hint_and_clamps_count():
    title, _arc, _ending, chapter_count, warnings = _parse_volume_json(
        {
            "title": "模型标题",
            "arc": "弧线",
            "ending": "收束",
            "chapter_count": 30,
        },
        number=2,
        title_hint="用户标题",
    )
    assert title == "用户标题"
    assert chapter_count == 20
    assert any("钳制" in w for w in warnings)


def test_parse_volume_json_missing_ending_raises():
    with pytest.raises(ValueError, match="ending"):
        _parse_volume_json(
            {"title": "T", "arc": "A", "ending": "   ", "chapter_count": 4},
            number=1,
            title_hint="",
        )


def test_parse_volume_chapters_json_happy_path():
    data = {
        "chapters": [
            {
                "title": "开端",
                "entities": ["char_a"],
                "tags": ["起"],
                "notes": "埋线",
                "purpose": "引入",
                "value_shift": "平静→不安",
                "tension": 2,
                "hook": "门外有人",
                "story_date": "第1日",
                "elapsed": "—",
                "beats": [
                    {
                        "goal": "抵达",
                        "conflict": "迷路",
                        "outcome": "找到客栈",
                        "entities": ["char_a"],
                    }
                ],
            },
            {
                "title": "升级",
                "entities": [],
                "tags": [],
                "notes": "",
                "purpose": "推进",
                "value_shift": "不安→危机",
                "tension": 4,
                "hook": "信使失踪",
                "story_date": "第2日",
                "elapsed": "一日",
                "beats": [
                    {
                        "goal": "追查",
                        "conflict": "线索断裂",
                        "outcome": "发现血印",
                        "entities": [],
                    }
                ],
            },
        ]
    }
    chapters, warnings = _parse_volume_chapters_json(
        data,
        volume=1,
        start_number=3,
        expected_count=2,
        codex=None,
    )
    assert len(chapters) == 2
    assert [c.number for c in chapters] == [3, 4]
    assert all(c.volume == 1 for c in chapters)
    assert chapters[0].title == "开端"
    assert chapters[0].beats[0].goal == "抵达"
    assert chapters[1].tension == 4
    assert warnings == []


def test_parse_volume_chapters_json_wrong_count_raises():
    data = {
        "chapters": [
            {
                "title": "仅一章",
                "beats": [{"goal": "g", "conflict": "c", "outcome": "o"}],
            }
        ]
    }
    with pytest.raises(ValueError, match="数量不符"):
        _parse_volume_chapters_json(
            data,
            volume=1,
            start_number=1,
            expected_count=3,
            codex=None,
        )
