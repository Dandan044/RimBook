"""Tests for planning-codex name identity, fuzzy dedup, and real-name gates."""

from __future__ import annotations

from rimbook.planning_entities import (
    ExpansionCandidate,
    NameRegistry,
    PlanningCodexChanges,
    PlanningCodexEntry,
    PlanningCodexService,
    WorldExpander,
    core_name,
    extract_real_names,
)
from rimbook.planning_entities.models import PlanningCodexProposal
from rimbook.planning_entities.store import PlanningEntityStore
from rimbook.project import scaffold_project


def _service(tmp_path):
    paths = scaffold_project(tmp_path / "project", exist_ok=True)
    return PlanningCodexService(PlanningEntityStore(paths))


def test_core_name_strips_parentheticals():
    assert core_name("净化者") == core_name("净化者（方舟计划内激进派系）")
    assert core_name("净化者(The Gardeners)") == core_name("净化者")


def test_extract_real_names_from_biography():
    text = "园丁，本名陆沉，出生于1990年。另称真名不详。"
    assert "陆沉" in extract_real_names(text)


def test_dedup_matches_parenthetical_rename(tmp_path):
    service = _service(tmp_path)
    expander = WorldExpander(service)
    service.store.save_entry(PlanningCodexEntry(
        id="faction_gardeners",
        name="净化者",
        type="faction",
    ))
    candidates = [
        ExpansionCandidate(
            provisional_id="faction_gardeners_purifiers",
            name="净化者（方舟计划内激进派系）",
            type="faction",
            source_entry_ids=["item_factor"],
            relatedness=0.85,
        ),
    ]
    accepted, _warnings = expander.deduplicate(candidates)
    assert len(accepted) == 1
    assert accepted[0].existing_match_id == "faction_gardeners"


def test_reconcile_merges_same_core_instead_of_creating(tmp_path):
    service = _service(tmp_path)
    service.store.save_entry(PlanningCodexEntry(
        id="faction_gardeners",
        name="净化者",
        type="faction",
        surface_summary="旧摘要",
    ))
    result = service.reconcile(
        PlanningCodexChanges(
            entries=[
                PlanningCodexProposal(
                    id="faction_gardeners_purifiers",
                    name="净化者（方舟计划内激进派系）",
                    type="faction",
                    surface_summary="新摘要",
                )
            ]
        ),
        source="world_expand",
    )
    assert result.created_entries == []
    assert "faction_gardeners" in result.updated_entries
    entry = service.store.get_entry("faction_gardeners")
    assert entry.surface_summary == "新摘要"
    ids = {e.id for e in service.store.list_entries("faction")}
    assert ids == {"faction_gardeners"}
    assert any("合并" in w for w in result.warnings)


def test_reconcile_rejects_cross_type_name_collision(tmp_path):
    service = _service(tmp_path)
    service.store.save_entry(PlanningCodexEntry(
        id="char_mc",
        name="陆沉",
        type="character",
    ))
    result = service.reconcile(
        PlanningCodexChanges(
            entries=[
                PlanningCodexProposal(
                    id="item_lu_chen",
                    name="陆沉",
                    type="item",
                    surface_summary="同名物品",
                )
            ]
        ),
        source="foundation",
    )
    assert result.created_entries == []
    assert any("占用" in w for w in result.warnings)


def test_detail_quality_rejects_occupied_real_name(tmp_path):
    service = _service(tmp_path)
    service.store.save_entry(PlanningCodexEntry(
        id="char_mc",
        name="陆沉",
        type="character",
        detail="主角陆沉的生平……" + ("补充。" * 40),
    ))
    service.store.save_entry(PlanningCodexEntry(
        id="char_gardener",
        name="园丁",
        type="character",
    ))
    detail = (
        "## 园丁深层生平\n\n"
        "园丁，本名陆沉，出生于1990年。他利用系统权限触发末日。\n\n"
        "童年经历塑造了他的极端信念，并最终走向净化行动。\n"
        + ("更多经历。" * 30)
    )
    issues = service.detail_quality_issues("char_gardener", detail)
    assert any("陆沉" in issue and "冲突" in issue for issue in issues)


def test_name_registry_find_match_containment():
    entries = [
        PlanningCodexEntry(id="faction_iron", name="铁拳帮", type="faction"),
    ]
    registry = NameRegistry.from_entries(entries)
    assert registry.find_match("铁拳帮派", "faction") == "faction_iron"
