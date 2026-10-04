"""OpenAI adapter (Chat Completions). Also works with any OpenAI-compatible server,
such as Ollama, through base_url."""

from __future__ import annotations

import json
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

from harnessy.models.openai_stream import merge_openai_chunks  # noqa: E402  (week 7)

PROVIDER = "openai"

_FINISH_REASONS: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "refused",
}


# --- Week 1 exercise -------------------------------------------------------------------


def map_openai_finish_reason(reason: str | None) -> StopReason:
    return _FINISH_REASONS.get(reason or "", "error")


def to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
        for t in tools
    ]


def to_openai_messages(messages: list[Message], system: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.text or (None if m.tool_calls else "")}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in m.tool_calls
                ]
            out.append(msg)
        else:
            for r in m.tool_results:
                content = f"ERROR: {r.content}" if r.is_error else r.content
                out.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": content})
            if m.text:
                out.append({"role": "user", "content": m.text})
    return out


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return value if isinstance(value, dict) else {"_raw": raw}


def from_openai_response(resp: dict[str, Any]) -> ModelResponse:
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = tuple(
        ToolCall(
            id=tc["id"],
            name=(tc.get("function") or {}).get("name", ""),
            arguments=_parse_arguments((tc.get("function") or {}).get("arguments") or "{}"),
        )
        for tc in msg.get("tool_calls") or []
    )
    usage = resp.get("usage") or {}
    return ModelResponse(
        message=Message(role="assistant", text=msg.get("content") or "", tool_calls=calls, raw=ProviderRaw(PROVIDER, msg)),
        stop_reason=map_openai_finish_reason(choice.get("finish_reason")),
        usage=Usage(usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0),
        raw=resp,
    )


# --- Given -----------------------------------------------------------------------------


class OpenAIModel:
    def __init__(self, model: str | None = None, client: Any | None = None, base_url: str | None = None):
        self.name = model or os.environ.get("OPENAI_MODEL") or ""
        if not self.name:
            raise ValueError("Set OPENAI_MODEL in .env to a current model that supports tool calling.")
        if client is None:
            import openai

            client = openai.OpenAI(base_url=base_url or os.environ.get("OPENAI_BASE_URL") or None)
        self._client = client

    def _request(self, messages: list[Message], tools: list[ToolSpec], system: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.name, "messages": to_openai_messages(messages, system)}
        if tools:  # the API rejects an empty tools array
            kwargs["tools"] = to_openai_tools(tools)
        return kwargs

    def complete(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None) -> ModelResponse:
        resp = self._client.chat.completions.create(**self._request(messages, tools, system))
        return from_openai_response(resp.model_dump(mode="json", exclude_none=True))

    def stream(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None):
        """Yield text chunks as they arrive, then the ModelResponse (week 7)."""
        chunks = []
        response = self._client.chat.completions.create(
            **self._request(messages, tools, system), stream=True, stream_options={"include_usage": True}
        )
        for chunk in response:
            data = chunk.model_dump(mode="json", exclude_none=True)
            chunks.append(data)
            for choice in data.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield text
        yield from_openai_response(merge_openai_chunks(chunks))
