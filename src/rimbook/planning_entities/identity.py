"""Name identity helpers for planning-codex dedup and collision checks.

World expansion historically only matched exact ``(type, normalize(name))``.
Models can bypass that by adding parentheticals (e.g. 「净化者（方舟计划内…）」)
or by inventing a 本名 that collides with another entry's display name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .models import PlanningCodexEntry
from .store import PlanningCodexStore

__all__ = [
    "NameRegistry",
    "NameOwner",
    "core_name",
    "extract_real_names",
    "normalize_name",
]

_PAREN_RE = re.compile(
    r"[（(【\[][^）)】\]]*[）)】\]]|"
    r"《[^》]*》"
)
_REAL_NAME_RE = re.compile(
    r"(?:本名|真名|原名|真实姓名|真实身份为)"
    r"(?:代号[^\s，,。；;（(]{0,8})?"
    r"[为是：:\s]*"
    r"[「『\"'“]?"
    r"([^\s，,。；;（)）\]】」』\"'”]{1,12})"
)
_MIN_CORE_LEN = 2


def normalize_name(value: str) -> str:
    """Lowercase and strip punctuation / whitespace for identity keys."""
    return re.sub(r"[\W_]+", "", value.strip().casefold())


def core_name(value: str) -> str:
    """Normalize after stripping parenthetical / bracketed decorations."""
    stripped = _PAREN_RE.sub("", value or "")
    return normalize_name(stripped)


def extract_real_names(text: str) -> list[str]:
    """Pull 本名/真名/原名 style labels out of free-form detail text."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _REAL_NAME_RE.finditer(text):
        raw = match.group(1).strip().strip("「」『』\"'“”")
        # Skip placeholder-ish fragments
        if not raw or raw in {"未知", "保密", "未公开", "不详"}:
            continue
        key = normalize_name(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(raw)
    return found


@dataclass(frozen=True)
class NameOwner:
    """One occupied surface name / alias / extracted real name."""

    entry_id: str
    entry_type: str
    display: str
    kind: str = "name"  # name | alias | real_name


@dataclass
class NameRegistry:
    """Occupied-name index for planning codex write paths and prompts."""

    owners_by_norm: dict[str, list[NameOwner]] = field(default_factory=dict)
    by_id: dict[str, PlanningCodexEntry] = field(default_factory=dict)

    @classmethod
    def from_store(cls, store: PlanningCodexStore) -> "NameRegistry":
        return cls.from_entries(store.list_entries())

    @classmethod
    def from_entries(cls, entries: Iterable[PlanningCodexEntry]) -> "NameRegistry":
        registry = cls()
        for entry in entries:
            registry.add_entry(entry)
        return registry

    def add_entry(self, entry: PlanningCodexEntry) -> None:
        self.by_id[entry.id] = entry
        self._register(entry.name, entry.id, entry.type, "name")
        for alias in entry.aliases:
            self._register(alias, entry.id, entry.type, "alias")
        for real in extract_real_names(entry.detail or ""):
            self._register(real, entry.id, entry.type, "real_name")

    def _register(
        self,
        display: str,
        entry_id: str,
        entry_type: str,
        kind: str,
    ) -> None:
        display = (display or "").strip()
        if not display:
            return
        for key in {normalize_name(display), core_name(display)}:
            if not key:
                continue
            owners = self.owners_by_norm.setdefault(key, [])
            if any(o.entry_id == entry_id and o.display == display for o in owners):
                continue
            owners.append(
                NameOwner(
                    entry_id=entry_id,
                    entry_type=entry_type,
                    display=display,
                    kind=kind,
                )
            )

    def owners_of(self, name: str) -> list[NameOwner]:
        keys = {normalize_name(name), core_name(name)}
        found: list[NameOwner] = []
        seen: set[tuple[str, str]] = set()
        for key in keys:
            if not key:
                continue
            for owner in self.owners_by_norm.get(key, []):
                token = (owner.entry_id, owner.display)
                if token in seen:
                    continue
                seen.add(token)
                found.append(owner)
        return found

    def is_occupied(
        self,
        name: str,
        *,
        type: str | None = None,
        exclude_id: str | None = None,
    ) -> bool:
        """True if name (or its core) is already used by another entry.

        When ``type`` is None, occupancy is cross-type (blocks 主角/反派同名).
        """
        for owner in self.owners_of(name):
            if exclude_id and owner.entry_id == exclude_id:
                continue
            if type is not None and owner.entry_type != type:
                continue
            return True
        if type is None:
            return False
        # Cross-type check when type was given for "same-type only" callers
        # is handled by callers via is_occupied(..., type=None).
        return False

    def find_match(
        self,
        name: str,
        entry_type: str,
        *,
        exclude_id: str | None = None,
    ) -> str:
        """Return an existing same-type entry id that matches name fuzzily.

        Order: exact normalize → core equality → core containment (same type).
        """
        exact = normalize_name(name)
        core = core_name(name)
        if not exact and not core:
            return ""

        # 1) Exact normalize / core equality via index
        for key in (exact, core):
            if not key:
                continue
            for owner in self.owners_by_norm.get(key, []):
                if owner.entry_type != entry_type:
                    continue
                if exclude_id and owner.entry_id == exclude_id:
                    continue
                return owner.entry_id

        # 2) Core containment against known same-type cores
        if len(core) < _MIN_CORE_LEN:
            return ""
        best_id = ""
        best_score = 0
        seen_ids: set[str] = set()
        for key, owners in self.owners_by_norm.items():
            if len(key) < _MIN_CORE_LEN:
                continue
            for owner in owners:
                if owner.entry_type != entry_type:
                    continue
                if exclude_id and owner.entry_id == exclude_id:
                    continue
                if owner.entry_id in seen_ids:
                    continue
                entry = self.by_id.get(owner.entry_id)
                entry_core = core_name(entry.name) if entry else key
                if not entry_core:
                    continue
                seen_ids.add(owner.entry_id)
                if core == entry_core:
                    return owner.entry_id
                shorter, longer = (
                    (core, entry_core)
                    if len(core) <= len(entry_core)
                    else (entry_core, core)
                )
                if shorter in longer and len(shorter) >= _MIN_CORE_LEN:
                    # Prefer stronger overlap (ratio of shorter/longer)
                    score = len(shorter) * 100 // max(len(longer), 1)
                    if score > best_score:
                        best_score = score
                        best_id = owner.entry_id
        # Require at least 50% overlap to avoid weak substring hits
        if best_score >= 50:
            return best_id
        return ""

    def allowed_names_for(self, entry_id: str) -> set[str]:
        """Normalized names this entry may freely reuse (own name/aliases/reals)."""
        entry = self.by_id.get(entry_id)
        if entry is None:
            return set()
        values = [entry.name, *entry.aliases, *extract_real_names(entry.detail or "")]
        return {normalize_name(v) for v in values if v and normalize_name(v)} | {
            core_name(v) for v in values if v and core_name(v)
        }

    def real_name_conflicts(
        self,
        entry_id: str,
        detail: str,
    ) -> list[str]:
        """Return issue strings when detail invents occupied real names."""
        allowed = self.allowed_names_for(entry_id)
        issues: list[str] = []
        for real in extract_real_names(detail):
            keys = {normalize_name(real), core_name(real)}
            if keys & allowed:
                continue
            for owner in self.owners_of(real):
                if owner.entry_id == entry_id:
                    continue
                issues.append(
                    f"详情中的真名/本名“{real}”与已有设定 "
                    f"{owner.entry_id}（{owner.display}）冲突，必须更换"
                )
                break
        return issues

    def render_occupied_block(self, *, max_chars: int = 3500) -> str:
        """Compact prompt block listing occupied display names."""
        if not self.by_id:
            return "（尚无已占用姓名）"
        lines = ["【已占用姓名——禁止复用为他人真名/本名/对外名或同义改名建档】"]
        type_order = (
            "character",
            "faction",
            "location",
            "item",
            "worldbuilding",
            "timeline",
        )
        entries = sorted(
            self.by_id.values(),
            key=lambda e: (type_order.index(e.type) if e.type in type_order else 99, e.id),
        )
        for entry in entries:
            extras: list[str] = []
            if entry.aliases:
                extras.append("别名：" + "、".join(entry.aliases[:6]))
            reals = extract_real_names(entry.detail or "")
            if reals:
                extras.append("已用真名：" + "、".join(reals[:4]))
            suffix = f"；{'；'.join(extras)}" if extras else ""
            lines.append(f"- [{entry.type}] {entry.id}（{entry.name}）{suffix}")
        text = "\n".join(lines)
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n…（已截断）"
