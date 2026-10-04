"""Anthropic adapter: translates harnessy types to the Messages API and back."""

from __future__ import annotations

import os
from typing import Any

from harnessy.types import (
    Message,
    ModelResponse,
    ProviderRaw,
    StopReason,
    ToolCall,
    ToolSpec,
    Usage,
)

PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-opus-5"
# Models that accept server-side refusal fallbacks ("default" routes by refusal category).
FALLBACK_MODELS = frozenset({"claude-opus-5", "claude-fable-5-1"})
MAX_TOKENS = 16000

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refused",
}


# --- Week 1 exercise -------------------------------------------------------------------


def map_anthropic_stop_reason(reason: str | None) -> StopReason:
    return _STOP_REASONS.get(reason or "", "error")


def to_anthropic_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "assistant":
            if m.raw is not None and m.raw.provider == PROVIDER:
                out.append({"role": "assistant", "content": m.raw.content})
                continue
            blocks: list[dict[str, Any]] = []
            if m.text:
                blocks.append({"type": "text", "text": m.text})
            for call in m.tool_calls:
                blocks.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
            if not blocks:
                blocks.append({"type": "text", "text": "(no output)"})
            out.append({"role": "assistant", "content": blocks})
        else:
            blocks = [
                {"type": "tool_result", "tool_use_id": r.tool_call_id, "content": r.content, "is_error": r.is_error}
                for r in m.tool_results
            ]
            if m.text:
                blocks.append({"type": "text", "text": m.text})
            out.append({"role": "user", "content": blocks})
    return out


def from_anthropic_response(resp: dict[str, Any]) -> ModelResponse:
    content = resp.get("content") or []
    text = "".join(b["text"] for b in content if b.get("type") == "text")
    calls = tuple(
        ToolCall(id=b["id"], name=b["name"], arguments=b.get("input") or {})
        for b in content
        if b.get("type") == "tool_use"
    )
    usage = resp.get("usage") or {}
    return ModelResponse(
        message=Message(role="assistant", text=text, tool_calls=calls, raw=ProviderRaw(PROVIDER, content)),
        stop_reason=map_anthropic_stop_reason(resp.get("stop_reason")),
        usage=Usage(usage.get("input_tokens") or 0, usage.get("output_tokens") or 0),
        raw=resp,
    )


# --- Given -----------------------------------------------------------------------------


class AnthropicModel:
    def __init__(self, model: str | None = None, client: Any | None = None, max_tokens: int = MAX_TOKENS):
        self.name = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self.max_tokens = max_tokens

    def _request(self, messages: list[Message], tools: list[ToolSpec], system: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.name,
            "max_tokens": self.max_tokens,
            "messages": to_anthropic_messages(messages),
        }
        if tools:
            kwargs["tools"] = to_anthropic_tools(tools)
        if system:
            kwargs["system"] = system
        if self.name in FALLBACK_MODELS:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["extra_body"] = {"fallbacks": "default"}
        return kwargs

    def complete(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None) -> ModelResponse:
        resp = self._client.beta.messages.create(**self._request(messages, tools, system))
        return from_anthropic_response(resp.model_dump(mode="json", by_alias=True, exclude_none=True))

    def stream(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None):
        """Yield text chunks as they arrive, then the ModelResponse (week 7)."""
        with self._client.beta.messages.stream(**self._request(messages, tools, system)) as stream:
            for text in stream.text_stream:
                yield text
            final = stream.get_final_message()
        yield from_anthropic_response(final.model_dump(mode="json", by_alias=True, exclude_none=True))
