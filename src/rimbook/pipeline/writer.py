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

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..codex import sync_codex_from_states, CodexStore
from ..config import GenerationConfig
from ..llm import LLMClient, Prompts
from ..llm.trace import NULL_TRACE, TraceStore
from ..memory import ContextAssembler, Summarizer
from ..outline import ChapterOutline, OutlineStore
from ..project import ProjectPaths
from ..memory.entity_state import EntityStateStore
from ..versioning import ProjectLock, VersionManager, atomic_write
from .post_write import PostWritePipeline, EnrichResult

__all__ = ["Writer", "WriteResult"]

logger = logging.getLogger("rimbook.writer")


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
        version_manager: VersionManager | None = None,
        trace: TraceStore | None = None,
        project_name: str = "",
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
        self.version_manager = version_manager
        self.trace = trace if trace is not None else NULL_TRACE
        self.project_name = project_name

    @property
    def _lock(self) -> ProjectLock:
        """Per-project file lock to prevent concurrent writes."""
        return ProjectLock(self.paths.root)

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
            trace=self.trace,
            project_name=self.project_name,
        )

    def write(self, number: int, *, persist: bool = True) -> WriteResult:
        """Generate (and persist) the draft for chapter *number*."""
        chapter = self.outline.read_chapter(number)
        if chapter is None:
            raise FileNotFoundError(f"Chapter {number} has no outline; run `plan chapter` first.")

        with self._lock:
            # ---- Rollback previous run's artifacts if re-generating ----
            # Use the *earliest* write-chN snapshot on this branch — that is the
            # true pre-first-write state.  Newer write-chN snapshots may be
            # polluted if a prior regen failed to delete post-write files
            # (see journal: restored=0, skipped=24, no deleted).
            draft_path = self.paths.draft_file(number)
            logger.warning(
                "ROLLBACK CHECK: ch=%d draft=%s vm=%s auto_cp=%s",
                number,
                draft_path.exists(),
                self.version_manager is not None,
                self.generation.auto_checkpoint,
            )
            if (
                persist
                and draft_path.exists()
                and self.version_manager is not None
                and self.generation.auto_checkpoint
            ):
                base_cp = _find_earliest_checkpoint(
                    self.version_manager, f"write-ch{number}-"
                )
                if base_cp:
                    affected = self._predict_affected_files(number, chapter)
                    # Only roll back entity state and codex files; draft and
                    # outline will be freshly generated anyway.
                    state_codex_files = [
                        f for f in affected
                        if _is_state_or_codex(f)
                    ]
                    logger.warning(
                        "ROLLBACK: checkpoint=%s affected=%d state_codex=%d",
                        base_cp.name, len(affected), len(state_codex_files),
                    )
                    if state_codex_files:
                        result = self.version_manager.restore_checkpoint(
                            base_cp.name, files=state_codex_files,
                            delete_missing=True,
                        )
                        logger.warning(
                            "ROLLBACK: result restored=%d skipped=%d deleted=%d "
                            "(from %s)",
                            result.get("restored", 0),
                            result.get("skipped", 0),
                            result.get("deleted", 0),
                            base_cp.name,
                        )
                        logger.info(
                            "Re-generating chapter %d: rolled back %d files "
                            "(state + codex) from checkpoint %s "
                            "(%d skipped, %d deleted — created by previous post-write)",
                            number,
                            result.get("restored", 0),
                            base_cp.name,
                            result.get("skipped", 0),
                            result.get("deleted", 0),
                        )
                else:
                    logger.warning(
                        "ROLLBACK: no checkpoint found for prefix write-ch%d-",
                        number,
                    )

            # Auto-checkpoint: snapshot the files that will be modified.
            if persist and self.version_manager is not None and self.generation.auto_checkpoint:
                affected = self._predict_affected_files(number, chapter)
                branch = self.version_manager.get_current_branch()
                self.version_manager.create_checkpoint(f"write-ch{number}-{branch}", affected)
                self.version_manager.prune(self.generation.max_checkpoints)

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
            with self.trace.begin("writer", project=self.project_name, chapter=number) as t:
                gen = self.llm.generate(
                    messages,
                    temperature=self.generation.temperature,
                    max_tokens=self.generation.max_tokens,
                )
                t.record(messages, gen, resolved_ids={
                    eid: eid for eid in chapter.all_entities()
                })
            draft = gen.content.strip()

            # 3. Persist draft + write-time context snapshot (atomic).
            draft_path = self.paths.draft_file(number)
            if persist:
                atomic_write(draft_path, draft + "\n")
                from ..memory.assembler import save_context_snapshot
                save_context_snapshot(self.paths, number, context)

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

        with self._lock:
            # Auto-checkpoint before revision.
            if persist and self.version_manager is not None and self.generation.auto_checkpoint:
                affected = self._predict_affected_files(number, chapter)
                branch = self.version_manager.get_current_branch()
                self.version_manager.create_checkpoint(f"revise-ch{number}-{branch}", affected)
                self.version_manager.prune(self.generation.max_checkpoints)

            context = self.assembler.assemble_for_chapter(chapter)
            user = self.prompts.writer_revise_user.format(
                number=number,
                context=context.text,
                draft_text=draft_text,
                instructions=instructions,
            )

            messages = self.llm.as_chat(system=self.prompts.writer_system, user=user)
            with self.trace.begin("revise", project=self.project_name, chapter=number) as t:
                gen = self.llm.generate(messages, temperature=0.7)
                t.record(messages, gen)
            revised = gen.content.strip()

            draft_path = self.paths.draft_file(number)
            if persist:
                atomic_write(draft_path, revised + "\n")
                from ..memory.assembler import save_context_snapshot
                save_context_snapshot(self.paths, number, context)

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

    def apply_minimal_fix(
        self,
        number: int,
        draft_text: str,
        issues_blob: str,
        *,
        persist: bool = True,
    ) -> str:
        """Targeted fix for checker issues, changing as little prose as possible.

        Unlike :meth:`revise` (a full rewrite with the complete writing
        context), this path uses the dedicated ``fix`` prompts: the model sees
        only the current prose + the audit issues and is instructed to touch
        nothing else — so auto-fix rounds don't drift the chapter's voice.
        Persists the fixed draft and re-runs the post-write pipeline so the
        summary / entity state stay in sync with the corrected text.
        """
        chapter = self.outline.read_chapter(number)
        if chapter is None:
            raise FileNotFoundError(f"Chapter {number} has no outline.")

        with self._lock:
            if persist and self.version_manager is not None and self.generation.auto_checkpoint:
                affected = self._predict_affected_files(number, chapter)
                branch = self.version_manager.get_current_branch()
                self.version_manager.create_checkpoint(f"fix-ch{number}-{branch}", affected)
                self.version_manager.prune(self.generation.max_checkpoints)

            messages = self.llm.as_chat(
                system=self.prompts.fix_system,
                user=self.prompts.fix_user.format(
                    chapter_text=draft_text,
                    issues=issues_blob,
                ),
            )
            with self.trace.begin("fix", project=self.project_name, chapter=number) as t:
                gen = self.llm.generate(messages, temperature=0.3)
                t.record(messages, gen)
            fixed = gen.content.strip()

            if persist:
                atomic_write(self.paths.draft_file(number), fixed + "\n")
                # Keep downstream artifacts (summary / state / codex) in sync.
                self._enricher.run(
                    number, fixed, chapter, enrich=self.generation.auto_enrich
                )
            return fixed

    def apply_minimal_fix(
        self,
        number: int,
        draft_text: str,
        issues_blob: str,
        *,
        persist: bool = True,
    ) -> str:
        """Targeted fix pass for the checker's auto-fix loop.

        Unlike :meth:`revise` (which re-writes the whole chapter with the
        full writing context), this uses the dedicated ``fix_*`` prompts:
        it only patches the passages related to the audit issues and keeps
        the rest of the prose — and its voice — untouched.
        """
        chapter = self.outline.read_chapter(number)
        if chapter is None:
            raise FileNotFoundError(f"Chapter {number} has no outline.")

        with self._lock:
            if persist and self.version_manager is not None and self.generation.auto_checkpoint:
                affected = self._predict_affected_files(number, chapter)
                branch = self.version_manager.get_current_branch()
                self.version_manager.create_checkpoint(f"fix-ch{number}-{branch}", affected)
                self.version_manager.prune(self.generation.max_checkpoints)

            user = self.prompts.fix_user.format(
                chapter_text=draft_text,
                issues=issues_blob,
            )
            messages = self.llm.as_chat(system=self.prompts.fix_system, user=user)
            with self.trace.begin("fix", project=self.project_name, chapter=number) as t:
                gen = self.llm.generate(messages, temperature=0.3)
                t.record(messages, gen)
            fixed = gen.content.strip()

            if persist:
                atomic_write(self.paths.draft_file(number), fixed + "\n")
                # Refresh the summary + entity state so downstream context
                # reflects the fixed text (enrichment/threads/memory already
                # ran on the original write of this chapter).
                self._enricher.run(number, fixed, chapter, enrich=False, light=True)

            return fixed

    def _predict_affected_files(self, number: int, chapter: ChapterOutline) -> list[Path]:
        """Predict the files that a write/revise of *number* will modify.

        Used by the auto-checkpoint to snapshot only the relevant files.
        We snapshot ALL entity state and codex files (not just those
        referenced in this chapter) so that branch forks from this
        checkpoint can fully reconstruct the pre-write state.
        """
        affected = [
            self.paths.draft_file(number),
            self.paths.context_snapshot_file(number),
            self.paths.chapter_outline(number),
            # Post-write may also touch the thread ledger and the rolling
            # story-so-far recap; snapshot them so rollback/forks stay clean.
            self.paths.threads_file,
            self.paths.story_so_far_file,
        ]
        # ALL entity state files (post-write pipeline may touch any of them).
        state_dir = self.paths.state_dir / "entities"
        if state_dir.exists():
            for sf in state_dir.glob("*.yaml"):
                affected.append(sf)
        # ALL codex entries (enricher may create / update any of them).
        for t in ("characters", "worldbuilding", "locations", "factions", "items", "timeline"):
            sd = self.paths.codex_subdir(t)
            if sd.exists():
                for cf in sd.glob("*.md"):
                    affected.append(cf)
        return affected


def _find_earliest_checkpoint(
    version_manager: VersionManager, label_prefix: str
) -> object | None:
    """Return the oldest checkpoint whose label starts with *label_prefix*.

    For chapter regen we need the *first* pre-write snapshot of that chapter
    (true baseline), not the newest — intermediate write-chN snapshots can
    contain post-write artefacts if an earlier regen failed to clean them.
    ``list_checkpoints`` returns newest-first, so the last match is oldest.
    """
    from ..versioning.manager import CheckpointInfo

    try:
        checkpoints: list[CheckpointInfo] = version_manager.list_checkpoints()
    except Exception:
        return None
    found = None
    for cp in checkpoints:
        if cp.label.startswith(label_prefix):
            found = cp
    return found


def _find_last_checkpoint(
    version_manager: VersionManager, label_prefix: str
) -> object | None:
    """Return the most recent checkpoint whose label starts with *label_prefix*."""
    from ..versioning.manager import CheckpointInfo

    try:
        checkpoints: list[CheckpointInfo] = version_manager.list_checkpoints()
    except Exception:
        return None
    for cp in checkpoints:
        if cp.label.startswith(label_prefix):
            return cp
    return None


def _is_state_or_codex(path: Path) -> bool:
    """Return True if *path* is an entity-state or codex file."""
    s = str(path).replace("\\", "/")
    return "/state/" in s or "/codex/" in s
