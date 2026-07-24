"""Tests for incomplete foundation-entry detection and label merge."""

from __future__ import annotations

from rimbook.planning_entities import (
    incomplete_entry_fields,
    merge_entry_labels,
    partition_raw_entries,
)
from rimbook.planning_entities import PlanningCodexChanges
from rimbook.planning_entities.models import PlanningCodexProposal
from rimbook.planning_entities.service import PlanningCodexService
from rimbook.planning_entities.store import PlanningEntityStore
from rimbook.project import scaffold_project


def test_incomplete_detects_blank_type_and_summaries():
    missing = incomplete_entry_fields(
        {
            "id": "location_001",
            "name": "锈蚀之城",
            "type": "",
            "exists_at_anchor": True,
        },
        require_existence=True,
    )
    assert "type" in missing
    assert "surface_summary" in missing
    assert "narrative_role" in missing
    assert "reveal_strategy" in missing
    assert "existence_reason" in missing


def test_partition_and_merge_relabel():
    raw = [
        {
            "id": "char_001",
            "name": "林远",
            "type": "character",
            "surface_summary": "主角",
            "narrative_role": "视角",
            "reveal_strategy": "开篇",
            "exists_at_anchor": True,
            "existence_reason": "故事开始时已存在",
            "secret_truth": "无",
        },
        {
            "id": "location_001",
            "name": "锈蚀之城",
            "type": "",
            "exists_at_anchor": True,
        },
    ]
    complete, incomplete = partition_raw_entries(raw, require_existence=True)
    assert len(complete) == 1
    assert len(incomplete) == 1
    assert incomplete[0]["id"] == "location_001"

    merged = merge_entry_labels(
        incomplete[0],
        {
            "id": "location_001",
            "type": "location",
            "surface_summary": "末日后的工业废城",
            "narrative_role": "主舞台",
            "reveal_strategy": "开篇城市全景",
            "existence_reason": "崩塌前已是工业都市",
            "secret_truth": "地下有旧实验室",
        },
    )
    assert incomplete_entry_fields(merged, require_existence=True) == []
    assert merged["type"] == "location"


def test_reconcile_refuses_blank_type_instead_of_defaulting(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    service = PlanningCodexService(PlanningEntityStore(paths))
    result = service.reconcile(
        PlanningCodexChanges(
            entries=[
                PlanningCodexProposal(
                    id="world_001",
                    name="灰烬纪元",
                    type="",
                    surface_summary="末日纪元名",
                )
            ]
        ),
        source="foundation",
    )
    assert result.created_entries == []
    assert any("缺少有效 type" in w for w in result.warnings)
    assert service.store.list_entries() == []


def test_apply_foundation_skips_blank_type(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    service = PlanningCodexService(PlanningEntityStore(paths))
    result = service.apply_foundation_entries(
        [
            {
                "id": "faction_001",
                "name": "重建派",
                "type": "",
                "surface_summary": "幸存者势力",
                "narrative_role": "对立阵营",
                "reveal_strategy": "第二章",
                "exists_at_anchor": True,
                "existence_reason": "聚落中已存在",
            }
        ],
        source="foundation",
        require_existence=True,
    )
    assert result.created_entries == []
    assert any("不完整" in w or "type" in w for w in result.warnings)
