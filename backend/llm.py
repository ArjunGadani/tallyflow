"""The ONE place Groq is called (§0). Used only for classify / extract /
categorize — never for math or matching.

A single `complete()` makes one call and returns the raw assistant text; JSON
parsing, schema validation, and repair live in extract.py/classify.py. Retry +
backoff is applied at the job level (retry.py, Phase 6), so this layer just
classifies failures as transient (429/5xx/timeout -> retry) or permanent.

Tests and offline runs inject a fake LLM implementing the `LLM` protocol; the
real GroqClient is lazy so importing this module never requires a key.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

from backend.config import get_settings


class LLMError(Exception):
    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class LLMImage:
    """One image for the vision path. `data` is raw bytes; mime e.g. image/png."""

    def __init__(self, data: bytes, mime: str = "image/png"):
        self.data = data
        self.mime = mime

    def to_data_url(self) -> str:
        b64 = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.mime};base64,{b64}"


class LLM(Protocol):
    def complete(
        self,
        model: str,
        system: str,
        user: str,
        images: Optional[Sequence[LLMImage]] = None,
        temperature: float = 0.0,
        json_mode: bool = True,
    ) -> str: ...


# --- Tool-calling layer (TallyChat). Separate from complete()/LLM so the
#     extraction path is untouched; GroqClient satisfies BOTH protocols. -------
@dataclass
class ToolSpec:
    """One tool the model may call. `parameters` is a JSON Schema object."""
    name: str
    description: str
    parameters: dict

    def to_openai(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters}}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatTurn:
    """Result of one chat turn: EITHER final text OR a batch of tool calls."""
    text: Optional[str] = None
    tool_calls: list = field(default_factory=list)        # list[ToolCall]
    raw_assistant_message: Optional[dict] = None          # appended verbatim to history
    usage: Optional[dict] = None


class ChatLLM(Protocol):
    def chat(self, model: str, messages: list, tools: Optional[Sequence[ToolSpec]] = None,
             temperature: float = 0.0, max_tokens: Optional[int] = None,
             tool_choice: str = "auto") -> ChatTurn: ...


class GroqClient:
    """Real Groq client (OpenAI-compatible chat completions). Implements both
    `LLM` (complete) and `ChatLLM` (chat with tools)."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or get_settings().groq_api_key
        self._client = None  # lazy

    def _ensure(self):
        if self._client is None:
            if not self._api_key:
                raise LLMError("GROQ_API_KEY not set", transient=False)
            from groq import Groq  # imported lazily so module import needs no key

            self._client = Groq(api_key=self._api_key)
        return self._client

    def complete(self, model, system, user, images=None, temperature=0.0, json_mode=True) -> str:
        client = self._ensure()
        # Vision messages embed images as base64 data URLs alongside the text.
        if images:
            content = [{"type": "text", "text": user}]
            for img in images:
                content.append({"type": "image_url", "image_url": {"url": img.to_data_url()}})
            user_message = {"role": "user", "content": content}
        else:
            user_message = {"role": "user", "content": user}

        kwargs = dict(
            model=model,
            messages=[{"role": "system", "content": system}, user_message],
            temperature=temperature,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as exc:  # map to transient/permanent for the retry layer
            transient = _is_transient(exc)
            raise LLMError(f"Groq call failed: {exc}", transient=transient) from exc

    def chat(self, model, messages, tools=None, temperature=0.0,
             max_tokens=None, tool_choice="auto") -> ChatTurn:
        """Tool-calling turn. Maps exceptions through the SAME transient/permanent
        path as complete() so with_retry actually retries (§7.5)."""
        client = self._ensure()
        kwargs = dict(model=model, messages=list(messages), temperature=temperature)
        if tools:
            kwargs["tools"] = [t.to_openai() for t in tools]
            kwargs["tool_choice"] = tool_choice
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"Groq chat failed: {exc}", transient=_is_transient(exc)) from exc

        msg = resp.choices[0].message
        calls = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}  # malformed args -> empty; the loop surfaces a tool error
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        raw = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else {
            "role": "assistant", "content": msg.content}
        usage = None
        if getattr(resp, "usage", None) is not None:
            usage = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage)
        return ChatTurn(text=(msg.content if not calls else None),
                        tool_calls=calls, raw_assistant_message=raw, usage=usage)


def _is_transient(exc: Exception) -> bool:
    """429 / 5xx / timeouts / connection errors are retryable; 4xx (bad request,
    auth) are not."""
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status == 429 or status >= 500
    name = type(exc).__name__.lower()
    return any(k in name for k in ("timeout", "connection", "ratelimit", "apiconnection"))


_singleton: Optional[GroqClient] = None


def get_llm() -> LLM:
    global _singleton
    if _singleton is None:
        _singleton = GroqClient()
    return _singleton
