"""Test doubles for the Groq boundary. Injecting a fake LLM at the `LLM`
protocol seam is the right kind of test double (an external API we don't own),
not a mock of our own logic."""
from __future__ import annotations

from typing import Optional, Sequence

from backend.llm import ChatTurn, LLMImage, ToolCall


class FakeLLM:
    """Returns scripted responses in order; records each call for assertions."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, model, system, user, images: Optional[Sequence[LLMImage]] = None,
                 temperature: float = 0.0, json_mode: bool = True) -> str:
        self.calls.append(
            {"model": model, "system": system, "user": user,
             "images": list(images) if images else None, "json_mode": json_mode}
        )
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


class RaisingLLM:
    """Always raises the given exception — for retry/dead-letter tests."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.calls = 0

    def complete(self, *a, **k) -> str:
        self.calls += 1
        raise self._exc

    def chat(self, *a, **k):
        self.calls += 1
        raise self._exc


# --- TallyChat tool-calling doubles ---------------------------------------
def tool_turn(calls: list) -> ChatTurn:
    """Build a ChatTurn requesting tool calls. `calls` is [(name, args_dict), ...]."""
    tcs = [ToolCall(id=f"call_{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)]
    return ChatTurn(text=None, tool_calls=tcs,
                    raw_assistant_message={"role": "assistant", "content": None,
                                           "tool_calls": [{"id": tc.id, "type": "function",
                                                           "function": {"name": tc.name, "arguments": "{}"}}
                                                          for tc in tcs]})


def text_turn(text: str) -> ChatTurn:
    """Build a ChatTurn with a final assistant answer (no tool calls)."""
    return ChatTurn(text=text, tool_calls=[],
                    raw_assistant_message={"role": "assistant", "content": text})


class FakeChatLLM:
    """Scripts a sequence of ChatTurns; each chat() pops the next. Records calls.
    Drives the agentic loop deterministically with no Groq/network."""

    def __init__(self, turns: list):
        self._turns = list(turns)
        self.calls: list[dict] = []

    def chat(self, model, messages, tools=None, temperature=0.0,
             max_tokens=None, tool_choice="auto") -> ChatTurn:
        self.calls.append({"model": model, "messages": list(messages),
                           "tools": [t.name for t in (tools or [])]})
        if not self._turns:
            raise AssertionError("FakeChatLLM ran out of scripted turns")
        return self._turns.pop(0)
