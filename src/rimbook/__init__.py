"""RimBook — LLM-powered long-form fiction writing workbench.

The core idea: rather than asking an LLM to "remember" an entire novel,
RimBook maintains a structured *Story Bible* (codex), a layered outline of
summaries, and a sliding window of recent prose. On every generation it
assembles only the most relevant, well-organized context and feeds it to the
LLM, then runs a write-check-fix loop to keep the story consistent.
"""

__version__ = "0.1.0"
