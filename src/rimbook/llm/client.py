"""OpenAI-compatible LLM client.

A thin wrapper around the ``openai`` SDK that:

* accepts ``base_url`` / ``api_key`` / ``model`` so it can target any
  OpenAI-compatible server (OpenAI, Azure, vLLM, Ollama's OpenAI shim, …),
* lets the caller pick a model per call (writing model vs. check model),
* exposes ``generate``, ``generate_json`` (for structured checker output),
* and ``embed`` for the retrieval layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from openai import OpenAI
from pydantic import BaseModel

from ..config import LLMConfig

__all__ = ["LLMClient", "Message", "GenerationResult"]


# Convenient message alias. Roles: "system" | "user" | "assistant".
Message = dict[str, str]


@dataclass
class GenerationResult:
    """The result of a chat completion."""

    content: str
    model: str
    usage: dict[str, int]  # {"prompt_tokens", "completion_tokens", "total_tokens"}


class LLMClient:
    """Stateless wrapper over the chat-completion + embedding endpoints."""

    def __init__(self, config: LLMConfig) -> None:
        if not config.api_key:
            # Many local servers ignore the key; allow an empty placeholder.
            api_key = "rimbook-no-key"
        else:
            api_key = config.api_key
        self._config = config
        self._client = OpenAI(base_url=config.base_url, api_key=api_key)
        # Embeddings may use a different endpoint/key; create lazily.
        self._embed_client: OpenAI | None = None

    @property
    def config(self) -> LLMConfig:
        return self._config

    @property
    def default_model(self) -> str:
        return self._config.model

    # ------------------------------------------------------------------
    # Chat completions
    # ------------------------------------------------------------------
    def generate(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        stop: list[str] | None = None,
    ) -> GenerationResult:
        """Run a chat completion and return the assistant text + usage."""
        used_model = model or self._config.model
        kwargs: dict[str, Any] = dict(
            model=used_model,
            messages=messages,  # type: ignore[arg-type]
        )
        # temperature / max_tokens live on GenerationConfig, not LLMConfig.
        # Only include them when the caller provides explicit values.
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if top_p is not None:
            kwargs["top_p"] = top_p
        if stop is not None:
            kwargs["stop"] = stop
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = {}
        if resp.usage is not None:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
        return GenerationResult(content=content, model=used_model, usage=usage)

    def generate_json(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Run a completion whose output should be a JSON object.

        We instruct the model to emit JSON and then parse defensively: if the
        model wrapped the JSON in code fences or prose, we try to extract the
        first ``{...}`` block. Raises ``ValueError`` when parsing fails.
        """
        messages = list(messages)
        # Reinforce JSON-only output as a trailing instruction.
        messages.append(
            {"role": "system", "content": "只输出合法的 JSON，不要任何额外文字或代码块标记。"}
        )
        result = self.generate(
            messages,
            model=model,
            temperature=0.0 if temperature is None else temperature,
        )
        return _extract_json(result.content)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def embed(self, texts: str | list[str]) -> list[list[float]]:
        """Embed one or more texts. Always returns a list of vectors."""
        if isinstance(texts, str):
            texts = [texts]
        emb = self._config.embedding
        # Use a separate client if embedding has its own base_url, else reuse the LLM client.
        client = self._get_embed_client()
        kwargs: dict[str, Any] = {"model": emb.model, "input": texts}
        if emb.dimensions is not None:
            kwargs["dimensions"] = emb.dimensions
        resp = client.embeddings.create(**kwargs)
        return [d.embedding for d in resp.data]

    def _get_embed_client(self):
        """Return the OpenAI client to use for embeddings.

        If the embedding config specifies a different base_url or api_key
        than the main LLM config, create a dedicated client; otherwise reuse.
        """
        emb = self._config.embedding
        emb_url = emb.resolved_base_url(self._config.base_url)
        emb_key = emb.resolved_api_key(self._config.api_key) or "rimbook-no-key"
        # If same endpoint, reuse main client.
        if emb_url == self._config.base_url and emb_key == (self._config.api_key or "rimbook-no-key"):
            return self._client
        # Different endpoint — create (and cache) a dedicated client.
        if self._embed_client is None:
            self._embed_client = OpenAI(base_url=emb_url, api_key=emb_key)
        return self._embed_client

    @property
    def embedding_model(self) -> str:
        return self._config.embedding.model

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def as_chat(
        self,
        system: str,
        user: str | None = None,
        history: Iterable[Message] = (),
    ) -> list[Message]:
        """Build a message list with a system prompt, optional history, user."""
        msgs: list[Message] = [{"role": "system", "content": system}]
        msgs.extend(history)
        if user is not None:
            msgs.append({"role": "user", "content": user})
        return msgs

    def check(self, messages: list[Message], **kw: Any) -> GenerationResult:
        """Like ``generate`` but on the (cheaper) check model."""
        return self.generate(messages, model=self._config.effective_check_model, **kw)


# ----------------------------------------------------------------------
# JSON extraction helpers
# ----------------------------------------------------------------------
def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from an LLM response."""
    text = text.strip()
    # Strip code fences if present.
    if text.startswith("```"):
        # Remove opening fence (with optional language tag) and closing fence.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Fall back to the first {...} balanced block.
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"无法从模型响应中解析 JSON。响应片段: {text[:200]!r}")
