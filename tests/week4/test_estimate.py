import json
import math

from harnessy.context import estimate_tokens
from harnessy.types import Message, ProviderRaw, ToolCall, ToolResult


def test_text_is_four_characters_per_token_rounded_up():
    assert estimate_tokens([Message("user", text="x" * 8)]) == 2
    assert estimate_tokens([Message("user", text="x" * 9)]) == 3
    assert estimate_tokens([]) == 0


def test_counts_tool_calls_and_results():
    call = Message("assistant", tool_calls=(ToolCall("c1", "add", {"a": 1}),))  # "add" + '{"a": 1}' = 11
    result = Message("user", tool_results=(ToolResult("c1", "42"),))  # 2
    assert estimate_tokens([call, result]) == math.ceil(13 / 4)


def test_raw_replaces_text_and_calls():
    raw = ProviderRaw("anthropic", [{"type": "text", "text": "hi"}])
    m = Message("assistant", text="hi" * 100, raw=raw)
    assert estimate_tokens([m]) == math.ceil(len(json.dumps(raw.content)) / 4)
