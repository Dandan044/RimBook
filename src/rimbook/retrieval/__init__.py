"""Retrieval layer: optional vector search to supplement explicit context.

The structured codex (loaded explicitly by entity id / tag) is the *spine*
of RimBook's context. Vector retrieval is a *supplement*: when a chapter's
beat touches themes or entities the author didn't tag explicitly, a
semantic query can surface related codex entries and chapter summaries that
would otherwise be missed.

We use ChromaDB (file-persisted) so it stays in the "pure files" spirit —
the index lives under ``state/vector/`` and can be rebuilt at any time from
the source Markdown.
"""

from .vector_store import VectorRetriever, VectorIndexer

__all__ = ["VectorRetriever", "VectorIndexer"]
