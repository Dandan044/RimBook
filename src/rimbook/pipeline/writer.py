"""The writer: turns a chapter beat into prose.

The writer is the orchestrator of the creative loop for a single chapter:

1. Load the chapter beat from the outline.
2. Ask the :class:`ContextAssembler` to build a focused context.
3. Call the LLM to draft the prose.
4. Summarize the draft + extract entity-state deltas.
5. Persist the draft to ``drafts/`` and update the outline summary + state.

The :class:`Checker` runs separately (or is invoked by the CLI), so a human
can review the draft before committing to consistency checks / fixes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..codex import sync_codex_from_states, CodexStore
from ..config import GenerationConfig
from ..llm import LLMClient, Prompts
from ..memory import ContextAssembler, Summarizer
from ..outline import ChapterOutline, OutlineStore
from ..project import ProjectPaths
from ..memory.entity_state import EntityStateStore
from .post_write import PostWritePipeline, EnrichResult

__all__ = ["Writer", "WriteResult"]


@dataclass
class WriteResult:
    """Outcome of writing one chapter."""

    chapter_number: int
    draft_path: str
    summary: str = ""
    context_preview: str = ""
    entities_tracked: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    enrichment: EnrichResult | None = None


class Writer:
    """Generate a chapter draft and its downstream artifacts."""

    def __init__(
        self,
        paths: ProjectPaths,
        *,
        llm: LLMClient,
        prompts: Prompts,
        outline: OutlineStore,
        assembler: ContextAssembler,
        summarizer: Summarizer,
        entity_state: EntityStateStore,
        codex: CodexStore,
        generation: GenerationConfig,
    ) -> None:
        self.paths = paths
        self.llm = llm
        self.prompts = prompts
        self.outline = outline
        self.assembler = assembler
        self.summarizer = summarizer
        self.entity_state = entity_state
        self.codex = codex
        self.generation = generation

    @property
    def _enricher(self) -> PostWritePipeline:
        """Lazily-constructed enrichment pipeline (avoids circular deps)."""
        return PostWritePipeline(
            llm=self.llm,
            prompts=self.prompts,
            codex=self.codex,
            entity_state=self.entity_state,
            summarizer=self.summarizer,
            generation=self.generation,
        )

    def write(self, number: int, *, persist: bool = True) -> WriteResult:
        """Generate (and persist) the draft for chapter *number*."""
        chapter = self.outline.read_chapter(number)
        if chapter is None:
            raise FileNotFoundError(f"Chapter {number} has no outline; run `plan chapter` first.")

        # 1. Assemble context.
        context = self.assembler.assemble_for_chapter(chapter)

        # 2. Generate.
        messages = self.llm.as_chat(
            system=self.prompts.writer_system,
            user=self.prompts.writer_user.format(
                number=number,
                context=context.text,
            ),
        )
        gen = self.llm.generate(
            messages,
            temperature=self.generation.temperature,
            max_tokens=self.generation.max_tokens,
        )
        draft = gen.content.strip()

        # 3. Persist draft.
        draft_path = self.paths.draft_file(number)
        if persist:
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(draft + "\n", encoding="utf-8")

        # 4. Run post-write pipeline: summarize + state + codex enrichment.
        enrich_result = self._enricher.run(
            number,
            draft,
            chapter,
            enrich=self.generation.auto_enrich,
        )
        entity_ids = chapter.all_entities()
        summary = ""
        tracked = list(entity_ids)
        try:
            # Re-read summary from disk (summarizer wrote it inside .run()).
            ch = self.outline.read_chapter(number)
            if ch and ch.summary:
                summary = ch.summary
        except Exception:
            pass

        return WriteResult(
            chapter_number=number,
            draft_path=str(draft_path),
            summary=summary,
            context_preview=context.text[:400] + ("…" if len(context.text) > 400 else ""),
            entities_tracked=tracked,
            usage=gen.usage,
            enrichment=enrich_result if self.generation.auto_enrich else None,
        )

    def revise(
        self,
        number: int,
        draft_text: str | None = None,
        *,
        instructions: str = "",
        persist: bool = True,
    ) -> WriteResult:
        """Revise an existing draft, optionally guided by *instructions*.

        Used by the checker's auto-fix loop and by the CLI ``revise`` command.
        """
        chapter = self.outline.read_chapter(number)
        if chapter is None:
            raise FileNotFoundError(f"Chapter {number} has no outline.")
        if draft_text is None:
            path = self.paths.draft_file(number)
            if not path.exists():
                raise FileNotFoundError(f"No draft for chapter {number}")
            draft_text = path.read_text(encoding="utf-8").strip()

        context = self.assembler.assemble_for_chapter(chapter)
        user = self.prompts.writer_revise_user.format(
            number=number,
            context=context.text,
            draft_text=draft_text,
            instructions=instructions,
        )

        messages = self.llm.as_chat(system=self.prompts.writer_system, user=user)
        gen = self.llm.generate(messages, temperature=0.7)
        revised = gen.content.strip()

        draft_path = self.paths.draft_file(number)
        if persist:
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(revised + "\n", encoding="utf-8")

        # Run post-write pipeline.
        enrich_result = self._enricher.run(
            number, revised, chapter, enrich=self.generation.auto_enrich
        )
        summary = ""
        try:
            ch = self.outline.read_chapter(number)
            if ch and ch.summary:
                summary = ch.summary
        except Exception:
            pass

        return WriteResult(
            chapter_number=number,
            draft_path=str(draft_path),
            summary=summary,
            context_preview="",
            entities_tracked=[],
            usage=gen.usage,
        )
