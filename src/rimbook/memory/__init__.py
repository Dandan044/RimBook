"""Memory layer: the heart of RimBook's consistency strategy.

The memory layer answers a single question on every generation: *"What
context should I feed the LLM right now?"* It composes four mechanisms:

* :mod:`window` — a sliding window of recent *full prose* chapters,
* :mod:`summarizer` — chapter summaries that stand in for older prose,
* :mod:`entity_state` — the *current* state of entities (who is where,
  who knows what) so characters don't contradict their own situation,
* :mod:`assembler` — ties the above together with codex + retrieval into
  a single, token-budgeted context blob.
"""

from .assembler import ContextAssembler, AssembledContext
from .entity_state import EntityStateStore, EntityState
from .summarizer import Summarizer
from .token_budget import estimate_tokens, BudgetAllocator, BudgetedItem
from .window import SlidingWindow

__all__ = [
    "ContextAssembler",
    "AssembledContext",
    "EntityStateStore",
    "EntityState",
    "Summarizer",
    "SlidingWindow",
    "estimate_tokens",
    "BudgetAllocator",
    "BudgetedItem",
]
