"""Configuration loading.

Two levels of configuration:

1. **Global workspace config** — ``{workspace_root}/.rimbook.yaml``.
   Holds LLM / embedding settings that apply to ALL projects in this workspace.
   Created automatically on first use with sensible defaults.

2. **Project config** — ``{project}/config.yaml``.
   Holds per-project settings: title, author, language, generation parameters.
   May also contain an ``llm`` section for backward compatibility, which takes
   precedence over the global config.

Merge order (highest to lowest):
  1. Environment variables (``RIMBOOK_*`` / ``OPENAI_API_KEY``)
  2. Project ``config.yaml`` (for backward-compat LLM overrides)
  3. Global ``.rimbook.yaml``
  4. Built-in defaults
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

__all__ = [
    "LLMConfig",
    "EmbeddingConfig",
    "GenerationConfig",
    "Config",
    "load_config",
    "load_global_config",
    "save_global_config",
    "GLOBAL_CONFIG_FILENAME",
    "DEFAULT_GLOBAL_CONFIG",
]

GLOBAL_CONFIG_FILENAME = ".rimbook.yaml"

# Built-in defaults for a fresh global config.
DEFAULT_GLOBAL_CONFIG: dict[str, Any] = {
    "llm": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "${LLM_API_KEY}",
        "model": "gpt-4o",
        "check_model": None,
        "reasoning_effort": None,
        "embedding": {
            "base_url": None,
            "api_key": None,
            "model": "text-embedding-3-small",
            "dimensions": None,
        },
    },
}


def _env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable, returning *default* when unset."""
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val


class EmbeddingConfig(BaseModel):
    """Configuration for the embedding endpoint (OpenAI-compatible)."""

    base_url: str | None = None
    api_key: str | None = None
    model: str = "text-embedding-3-small"
    dimensions: int | None = None

    def resolved_base_url(self, fallback: str) -> str:
        url = self.base_url or fallback
        if url.rstrip("/").endswith("/embeddings"):
            url = url.rstrip("/")[: -len("/embeddings")]
        return url

    def resolved_api_key(self, fallback: str | None) -> str | None:
        return self.api_key or fallback


class LLMConfig(BaseModel):
    """Configuration for the chat-completion endpoint (OpenAI-compatible)."""

    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    model: str = "gpt-4o"
    check_model: str | None = None
    reasoning_effort: str | None = None  # "low" | "medium" | "high" | None
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

    @property
    def effective_check_model(self) -> str:
        return self.check_model or self.model


class GenerationConfig(BaseModel):
    """Knobs that control context assembly and the write-check loop."""

    temperature: float = 0.85
    max_tokens: int = 40000
    recent_window_chapters: int = 1
    summary_history: int = 6
    auto_consistency_check: bool = True
    auto_fix: bool = False
    max_fix_rounds: int = 2
    top_p: float = 1.0
    codex_max_tokens: int = 2000
    codex_entry_max_chars: int = 1500
    auto_enrich: bool = True  # LLM-driven codex enrichment after each chapter
    auto_checkpoint: bool = True  # auto-checkpoint before each write/revise
    max_checkpoints: int = 50  # prune oldest checkpoints beyond this count


class Config(BaseModel):
    """The full, resolved configuration for a novel project."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    title: str = "Untitled Novel"
    author: str = ""
    language: str = "zh"


# ---------------------------------------------------------------------------
# Global workspace config
# ---------------------------------------------------------------------------
def _global_config_path(workspace_root: Path) -> Path:
    return workspace_root / GLOBAL_CONFIG_FILENAME


def load_global_config(workspace_root: Path | None = None) -> dict[str, Any]:
    """Load the global workspace config, creating it with defaults if missing.

    Args:
        workspace_root: Directory containing projects. Defaults to the
            current working directory or ``RIMBOOK_WORKSPACE`` env var.
    """
    if workspace_root is None:
        workspace_root = _workspace_root()
    path = _global_config_path(workspace_root)
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
            if isinstance(loaded, dict):
                return _walk_expand(loaded)
    # Create with defaults.
    _write_global_config(path, DEFAULT_GLOBAL_CONFIG)
    return _walk_expand(dict(DEFAULT_GLOBAL_CONFIG))


def save_global_config(data: dict[str, Any], workspace_root: Path | None = None) -> Path:
    """Persist the global workspace config."""
    if workspace_root is None:
        workspace_root = _workspace_root()
    path = _global_config_path(workspace_root)
    _write_global_config(path, data)
    return path


def _write_global_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Project config loading (merged with global)
# ---------------------------------------------------------------------------
def load_config(project_dir: Path, *, global_cfg: dict[str, Any] | None = None) -> Config:
    """Load configuration for a project, merging global defaults underneath.

    Resolution order:
      1. Environment variables (highest)
      2. Project ``config.yaml`` (backward-compat LLM overrides)
      3. Global ``.rimbook.yaml``
      4. Built-in defaults
    """
    if global_cfg is None:
        global_cfg = _load_global_for_project(project_dir)

    cfg_path = project_dir / "config.yaml"
    project_raw: dict[str, Any] = {}
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{cfg_path}: top-level YAML must be a mapping")
        project_raw = _walk_expand(loaded)

    # Merge: project overrides global.
    merged_llm = dict(global_cfg.get("llm", {}))
    project_llm = project_raw.get("llm", {}) or {}
    _deep_merge(merged_llm, project_llm)

    # --- LLM -------------------------------------------------------------
    llm = _build_llm_config(merged_llm)

    # --- Generation ------------------------------------------------------
    gen_raw = project_raw.get("generation", {}) or {}
    generation = GenerationConfig(
        temperature=gen_raw.get("temperature", 0.85),
        max_tokens=gen_raw.get("max_tokens", 40000),
        recent_window_chapters=gen_raw.get("recent_window_chapters", 1),
        summary_history=gen_raw.get("summary_history", 6),
        auto_consistency_check=gen_raw.get("auto_consistency_check", True),
        auto_fix=gen_raw.get("auto_fix", False),
        max_fix_rounds=gen_raw.get("max_fix_rounds", 2),
        top_p=gen_raw.get("top_p", 1.0),
        codex_max_tokens=gen_raw.get("codex_max_tokens", 2000),
        codex_entry_max_chars=gen_raw.get("codex_entry_max_chars", 1500),
        auto_enrich=gen_raw.get("auto_enrich", True),
        auto_checkpoint=gen_raw.get("auto_checkpoint", True),
        max_checkpoints=gen_raw.get("max_checkpoints", 50),
    )

    return Config(
        llm=llm,
        generation=generation,
        title=project_raw.get("title", "Untitled Novel"),
        author=project_raw.get("author", ""),
        language=project_raw.get("language", "zh"),
    )


def _load_global_for_project(project_dir: Path) -> dict[str, Any]:
    """Discover the workspace root from *project_dir* and load global config."""
    # Walk up to find a directory that looks like a workspace (contains
    # .rimbook.yaml) or use the project's parent.
    candidate = project_dir.resolve()
    for d in [candidate, *candidate.parents]:
        if (_global_config_path(d)).exists():
            return load_global_config(d)
    # No global config found — create one in the project's grandparent
    # (or parent if that's the workspace root).
    ws = candidate.parent  # default: workspace root = parent of project dir
    return load_global_config(ws)


# ---------------------------------------------------------------------------
# LLM config builder
# ---------------------------------------------------------------------------
def _build_llm_config(raw: dict[str, Any]) -> LLMConfig:
    base_url = raw.get("base_url") or _env(
        "RIMBOOK_BASE_URL", "https://api.openai.com/v1"
    )
    api_key = raw.get("api_key") or _env("RIMBOOK_API_KEY") or _env("OPENAI_API_KEY")
    model = raw.get("model") or _env("RIMBOOK_MODEL", "gpt-4o")
    check_model = raw.get("check_model") or _env("RIMBOOK_CHECK_MODEL")

    emb_raw = raw.get("embedding", {}) or {}
    embedding = EmbeddingConfig(
        base_url=emb_raw.get("base_url") or _env("RIMBOOK_EMBED_BASE_URL"),
        api_key=emb_raw.get("api_key") or _env("RIMBOOK_EMBED_API_KEY") or api_key,
        model=emb_raw.get("model") or _env("RIMBOOK_EMBED_MODEL", "text-embedding-3-small"),
        dimensions=emb_raw.get("dimensions"),
    )

    return LLMConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        check_model=check_model,
        reasoning_effort=raw.get("reasoning_effort") or None,
        embedding=embedding,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _workspace_root() -> Path:
    env = os.environ.get("RIMBOOK_WORKSPACE")
    return Path(env).resolve() if env else Path.cwd()


def _deep_merge(target: dict, source: dict) -> None:
    """Merge *source* into *target* in-place, recursing into nested dicts."""
    for k, v in source.items():
        if k in target and isinstance(target[k], dict) and isinstance(v, dict):
            _deep_merge(target[k], v)
        elif v is not None:
            target[k] = v


def _expand_env(value: Any) -> Any:
    """Expand ``${VAR}`` references inside string values read from YAML."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("${") and stripped.endswith("}"):
            return _env(stripped[2:-1])
        return value
    return value


def _walk_expand(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _walk_expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_expand(v) for v in obj]
    return _expand_env(obj)
