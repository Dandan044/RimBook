"""Pipeline layer: the write-check-fix workflow.

Three collaborators implement the core creative loop:

* :class:`Planner` — produces synopsis / volume / chapter beats,
* :class:`Writer`  — turns a chapter beat into prose, then summarizes +
  updates entity state,
* :class:`Checker` — audits prose against codex + summaries and, optionally,
  drives an auto-fix loop.

Each stage writes its output to disk as a checkpoint, so a human can review
and edit between stages.
"""

from .planner import Planner
from .writer import Writer, WriteResult
from .checker import Checker, CheckReport, Issue
from .post_write import PostWritePipeline, EnrichResult, EnrichmentChange

__all__ = [
    "Planner",
    "Writer",
    "WriteResult",
    "Checker",
    "CheckReport",
    "Issue",
    "PostWritePipeline",
    "EnrichResult",
    "EnrichmentChange",
]
