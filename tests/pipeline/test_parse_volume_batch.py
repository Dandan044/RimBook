"""Pure-dict tests for volume JSON parser (no LLM)."""

from __future__ import annotations

import pytest

from rimbook.pipeline.planner import _parse_volume_json


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
