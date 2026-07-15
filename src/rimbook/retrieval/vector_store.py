"""Vector store backed by ChromaDB.

ChromaDB persists to disk under ``state/vector/``. We keep two logical
collections:

* ``codex``       — one document per codex entry (id, name+aliases, body),
* ``summaries``   — one document per chapter summary.

Embeddings are produced via the :class:`LLMClient` (OpenAI-compatible), and
passed to Chroma with ``embedding_function`` bypassed (we compute and store
vectors ourselves) so any OpenAI-compatible embedding endpoint works
regardless of Chroma's bundled providers.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..codex import CodexStore
from ..llm import LLMClient
from ..outline import OutlineStore
from ..project import ProjectPaths

__all__ = ["VectorIndexer", "VectorRetriever"]

# ChromaDB import is deferred so the rest of RimBook works without it
# installed (structured-codex-only mode). The indexer/retriever will raise a
# clear error if used without chromadb available.


def _require_chroma():
    try:
        import chromadb  # noqa: F401
        from chromadb import PersistentClient  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Vector retrieval requires the 'chromadb' package. "
            "Install it with: pip install chromadb"
        ) from exc
    return chromadb


class _ChromaBase:
    """Shared Chroma client + collection access."""

    def __init__(self, paths: ProjectPaths, llm: LLMClient) -> None:
        chromadb = _require_chroma()
        self.paths = paths
        self.llm = llm
        self.vector_dir = paths.vector_dir
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.vector_dir))

    def _collection(self, name: str):
        return self._client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )


class VectorIndexer(_ChromaBase):
    """Build / refresh the vector index from source files."""

    def rebuild(self, *, codex: CodexStore, outline: OutlineStore) -> dict[str, int]:
        """Drop and rebuild both collections. Returns counts."""
        counts = {}
        counts["codex"] = self._index_codex(codex)
        counts["summaries"] = self._index_summaries(outline)
        return counts

    def update_codex_entry(self, entry) -> None:
        """Upsert a single codex entry into the index."""
        col = self._collection("codex")
        text = _codex_text(entry)
        vec = self.llm.embed(text)[0]
        col.upsert(
            ids=[entry.id],
            embeddings=[vec],
            documents=[text],
            metadatas=[{"id": entry.id, "name": entry.name, "type": entry.type}],
        )

    def update_summary(self, number: int, title: str, summary: str) -> None:
        """Upsert a single chapter summary into the index."""
        col = self._collection("summaries")
        text = f"第{number}章：{summary}"
        vec = self.llm.embed(text)[0]
        col.upsert(
            ids=[f"ch{number:03d}"],
            embeddings=[vec],
            documents=[text],
            metadatas=[{"chapter": number, "title": title}],
        )

    # ------------------------------------------------------------------
    def _index_codex(self, codex: CodexStore) -> int:
        # Recreate fresh.
        try:
            self._client.delete_collection("codex")
        except Exception:
            pass
        col = self._collection("codex")
        entries = list(codex.iter_all())
        if not entries:
            return 0
        texts = [_codex_text(e) for e in entries]
        vectors = self.llm.embed(texts)
        col.add(
            ids=[e.id for e in entries],
            embeddings=vectors,
            documents=texts,
            metadatas=[
                {"id": e.id, "name": e.name, "type": e.type} for e in entries
            ],
        )
        return len(entries)

    def _index_summaries(self, outline: OutlineStore) -> int:
        try:
            self._client.delete_collection("summaries")
        except Exception:
            pass
        col = self._collection("summaries")
        chapters = [c for c in outline.list_chapters() if c.summary.strip()]
        if not chapters:
            return 0
        texts = [
            f"第{c.number}章：{c.summary.strip()}" for c in chapters
        ]
        vectors = self.llm.embed(texts)
        ids = [f"ch{c.number:03d}" for c in chapters]
        col.add(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=[{"chapter": c.number, "title": c.title} for c in chapters],
        )
        return len(chapters)


class VectorRetriever(_ChromaBase):
    """Query the vector index for related codex entries / summaries."""

    def query(self, text: str, *, k: int = 5, collection: str = "codex") -> list[dict[str, Any]]:
        """Return up to *k* hits from *collection* for the query text."""
        col = self._collection(collection)
        if col.count() == 0:
            return []
        vec = self.llm.embed(text)[0]
        res = col.query(query_embeddings=[vec], n_results=k)
        return _format_hits(res)

    def query_codex(self, text: str, k: int = 5) -> list[dict[str, Any]]:
        return self.query(text, k=k, collection="codex")

    def query_summaries(self, text: str, k: int = 5) -> list[dict[str, Any]]:
        return self.query(text, k=k, collection="summaries")


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _codex_text(entry) -> str:
    parts = [entry.name]
    if entry.aliases:
        parts.append("（别名：" + "、".join(entry.aliases) + "）")
    parts.append(entry.body.strip())
    return "\n".join(p for p in parts if p)


def _format_hits(res: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ids_batch = (res.get("ids") or [[]])[0]
    docs_batch = (res.get("documents") or [[]])[0]
    meta_batch = (res.get("metadatas") or [[]])[0]
    dist_batch = (res.get("distances") or [[]])[0]
    for i in range(len(ids_batch)):
        meta = meta_batch[i] if i < len(meta_batch) else {}
        out.append(
            {
                "id": meta.get("id") or ids_batch[i],
                "document": docs_batch[i] if i < len(docs_batch) else "",
                "metadata": meta,
                "distance": dist_batch[i] if i < len(dist_batch) else None,
            }
        )
    return out
