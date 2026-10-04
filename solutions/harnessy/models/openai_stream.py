"""Streaming for the OpenAI adapter (week 7): tool calls arrive in fragments, spread over many
chunks. Put them back together into the same dict a non-streaming call returns."""

from __future__ import annotations

from typing import Any

# --- Week 7 exercise -------------------------------------------------------------------


def merge_openai_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild a non-streaming Chat Completions response from streamed chunks, so
    from_openai_response can parse it unchanged:

    {"id": <first chunk's id>, "model": <first chunk's model>,
     "choices": [{"index": 0, "message": {...}, "finish_reason": <last non-null finish_reason>}],
     "usage": <the chunk that has usage, else {}>}

    message: {"role": "assistant", "content": <all delta content joined, or None if there was
    none>, "tool_calls": [...]} — leave the "tool_calls" key out if there were none.
    Tool calls arrive as fragments keyed by "index": keep the first id, type and function name
    seen for each index, and concatenate the function "arguments" fragments in order. Output
    them sorted by index, each as {"id", "type", "function": {"name", "arguments"}}.
    A chunk may have an empty "choices" list (the usage chunk).
    """
    first = chunks[0] if chunks else {}
    content: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    finish = None
    usage: dict[str, Any] = {}
    for chunk in chunks:
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
            for fragment in delta.get("tool_calls") or []:
                slot = calls.setdefault(
                    fragment.get("index", 0), {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if fragment.get("id") and not slot["id"]:
                    slot["id"] = fragment["id"]
                if fragment.get("type"):
                    slot["type"] = fragment["type"]
                fn = fragment.get("function") or {}
                if fn.get("name") and not slot["function"]["name"]:
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    message: dict[str, Any] = {"role": "assistant", "content": "".join(content) or None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {
        "id": first.get("id"),
        "model": first.get("model"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": usage,
    }
