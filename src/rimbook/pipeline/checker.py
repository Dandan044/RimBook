"""The checker: consistency auditing + optional auto-fix loop.

After a chapter is written, the checker compares the prose against the
codex, the recent summaries, and the chapter beat, and reports any
inconsistencies. With ``auto_fix`` enabled it feeds those issues back into
the writer for a bounded number of revision rounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..llm import LLMClient, Prompts
from ..project import ProjectPaths

__all__ = ["Issue", "CheckReport", "Checker"]


@dataclass
class Issue:
    """One inconsistency flagged by the checker."""

    severity: str  # high | medium | low
    category: str  # setting | character | plot | fact
    description: str
    evidence: str = ""
    suggestion: str = ""

    @property
    def is_blocking(self) -> bool:
        return self.severity in ("high", "medium")


@dataclass
class CheckReport:
    """The full result of checking one chapter."""

    chapter_number: int
    overall: str = "通过"  # 通过 | 需修订 | 严重问题
    summary: str = ""
    issues: list[Issue] = field(default_factory=list)
    rounds: int = 0  # number of fix rounds actually performed
    final_text: str = ""  # final prose after any auto-fix
    usage: list[dict[str, int]] = field(default_factory=list)

    @property
    def blocking_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.is_blocking]

    @property
    def passed(self) -> bool:
        return not self.blocking_issues and self.overall == "通过"


class Checker:
    """Audit chapter prose for consistency and optionally auto-fix."""

    def __init__(self, paths: ProjectPaths, *, llm: LLMClient, prompts: Prompts) -> None:
        self.paths = paths
        self.llm = llm
        self.prompts = prompts

    def check(self, number: int, draft_text: str | None = None) -> CheckReport:
        """Audit a chapter's draft and return a :class:`CheckReport`."""
        if draft_text is None:
            path = self.paths.draft_file(number)
            if not path.exists():
                raise FileNotFoundError(f"No draft for chapter {number}")
            draft_text = path.read_text(encoding="utf-8").strip()

        report = CheckReport(chapter_number=number, final_text=draft_text)
        self._run_one_pass(report, draft_text)
        return report

    def check_and_fix(
        self,
        number: int,
        *,
        max_rounds: int,
        apply_fix,
        draft_text: str | None = None,
    ) -> CheckReport:
        """Run check, then call *apply_fix(text, issues)* up to *max_rounds* times.

        ``apply_fix`` is a callable that takes the current prose + issues and
        returns revised prose (typically bound to :meth:`Writer.revise`).
        """
        if draft_text is None:
            path = self.paths.draft_file(number)
            if not path.exists():
                raise FileNotFoundError(f"No draft for chapter {number}")
            draft_text = path.read_text(encoding="utf-8").strip()

        report = CheckReport(chapter_number=number, final_text=draft_text)
        self._run_one_pass(report, draft_text)

        rounds = 0
        while not report.passed and rounds < max_rounds:
            rounds += 1
            issues_blob = self._format_issues_for_fix(report.issues)
            revised = apply_fix(draft_text, issues_blob)
            report.final_text = revised
            report.issues = []
            report.rounds = rounds
            self._run_one_pass(report, revised)
            draft_text = revised

        report.rounds = rounds
        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _run_one_pass(self, report: CheckReport, text: str) -> None:
        user = self.prompts.checker_user.format(chapter_text=text)
        messages = self.llm.as_chat(system=self.prompts.checker_system, user=user)
        data = self.llm.generate_json(
            messages,
            model=self.llm.config.effective_check_model,
            temperature=0.0,
        )
        if "usage" in data and isinstance(data["usage"], dict):
            report.usage.append(data["usage"])  # type: ignore[arg-type]
        report.overall = str(data.get("overall", "需修订")) or "需修订"
        report.summary = str(data.get("summary", "") or "")
        issues: list[Issue] = []
        for raw in data.get("issues") or []:
            if not isinstance(raw, dict):
                continue
            issues.append(
                Issue(
                    severity=str(raw.get("severity", "low")).lower(),
                    category=str(raw.get("category", "fact")).lower(),
                    description=str(raw.get("description", "")).strip(),
                    evidence=str(raw.get("evidence", "")).strip(),
                    suggestion=str(raw.get("suggestion", "")).strip(),
                )
            )
        report.issues = issues

    @staticmethod
    def _format_issues_for_fix(issues: list[Issue]) -> str:
        if not issues:
            return "(无)"
        lines = []
        for i, iss in enumerate(issues, 1):
            lines.append(
                f"{i}. [{iss.severity}/{iss.category}] {iss.description}"
                + (f"\n   证据：{iss.evidence}" if iss.evidence else "")
                + (f"\n   建议：{iss.suggestion}" if iss.suggestion else "")
            )
        return "\n".join(lines)
