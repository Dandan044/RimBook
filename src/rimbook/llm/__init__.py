"""LLM layer: OpenAI-compatible client + centralized prompt templates."""

from .client import LLMClient
from .prompts import Prompts
from .prompts_store import (
    PROMPT_KEYS,
    PROMPT_META,
    catalog,
    default_prompts_dict,
    list_overrides,
    load_default_prompts,
    load_prompts,
    render_preview,
    reset_all_overrides,
    save_prompts_overrides,
)

__all__ = [
    "LLMClient",
    "Prompts",
    "PROMPT_KEYS",
    "PROMPT_META",
    "catalog",
    "default_prompts_dict",
    "list_overrides",
    "load_default_prompts",
    "load_prompts",
    "render_preview",
    "reset_all_overrides",
    "save_prompts_overrides",
]
