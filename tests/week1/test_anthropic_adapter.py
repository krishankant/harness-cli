from types import SimpleNamespace

import pytest

from harnessy.models.anthropic import (
    AnthropicModel,
    from_anthropic_response,
    map_anthropic_stop_reason,
    to_anthropic_messages,
    to_anthropic_tools,
)
from harnessy.types import Message, ProviderRaw, ToolCall, ToolResult, ToolSpec

ADD = ToolSpec("add", "Add two integers.", {"type": "object", "properties": {"a": {"type": "integer"}}})


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("end_turn", "end_turn"),
        ("stop_sequence", "end_turn"),
        ("tool_use", "tool_use"),
        ("max_tokens", "max_tokens"),
        ("refusal", "refused"),
        ("pause_turn", "error"),
        (None, "error"),
    ],
)
def test_map_stop_reason(reason, expected):
    assert map_anthropic_stop_reason(reason) == expected


def test_tools_use_input_schema():
    assert to_anthropic_tools([ADD]) == [
        {"name": "add", "description": "Add two integers.", "input_schema": ADD.parameters}
    ]


def test_user_text_becomes_text_block():
    assert to_anthropic_messages([Message(role="user", text="hi")]) == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    ]


def test_assistant_without_raw_is_rebuilt():
    m = Message(role="assistant", text="ok", tool_calls=(ToolCall("t1", "add", {"a": 1}),))
    assert to_anthropic_messages([m]) == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "id": "t1", "name": "add", "input": {"a": 1}},
            ],
        }
    ]


def test_assistant_raw_from_anthropic_is_replayed_verbatim(load_fixture):
    content = load_fixture("anthropic_tool_use.json")["content"]
    m = Message(role="assistant", text="ignored", raw=ProviderRaw("anthropic", content))
    assert to_anthropic_messages([m]) == [{"role": "assistant", "content": content}]


def test_raw_from_another_provider_is_ignored():
    m = Message(role="assistant", text="hi", raw=ProviderRaw("openai", {"role": "assistant"}))
    assert to_anthropic_messages([m])[0]["content"] == [{"type": "text", "text": "hi"}]


def test_tool_results_come_first_in_user_turn():
    m = Message(
        role="user",
        text="also this",
        tool_results=(ToolResult("t1", "42"), ToolResult("t2", "boom", is_error=True)),
    )
    assert to_anthropic_messages([m]) == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "42", "is_error": False},
                {"type": "tool_result", "tool_use_id": "t2", "content": "boom", "is_error": True},
                {"type": "text", "text": "also this"},
            ],
        }
    ]


def test_parse_tool_use_response_keeps_raw_and_skips_thinking(load_fixture):
    resp = load_fixture("anthropic_tool_use.json")
    r = from_anthropic_response(resp)
    assert r.stop_reason == "tool_use"
    assert r.message.role == "assistant"
    assert r.message.text == "Let me add those."
    assert r.message.tool_calls == (ToolCall("toolu_01", "add", {"a": 17, "b": 25}),)
    assert r.message.raw == ProviderRaw("anthropic", resp["content"])
    assert (r.usage.input_tokens, r.usage.output_tokens) == (120, 40)
    assert r.raw == resp


def test_parse_joins_text_blocks(load_fixture):
    r = from_anthropic_response(load_fixture("anthropic_end_turn.json"))
    assert r.message.text == "17 + 25 = 42."
    assert r.message.tool_calls == ()
    assert r.stop_reason == "end_turn"


def test_parse_refusal(load_fixture):
    r = from_anthropic_response(load_fixture("anthropic_refusal.json"))
    assert r.stop_reason == "refused"
    assert r.message.text == ""


def _fake_client(captured: dict):
    reply = SimpleNamespace(model_dump=lambda **kw: {"content": [{"type": "text", "text": "hi"}],
                                                   "stop_reason": "end_turn",
                                                   "usage": {"input_tokens": 1, "output_tokens": 1}})

    def create(**kwargs):
        captured.update(kwargs)
        return reply

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_complete_omits_empty_tools_and_sends_fallbacks_for_opus():
    captured: dict = {}
    model = AnthropicModel(model="claude-opus-5", client=_fake_client(captured))
    r = model.complete([Message(role="user", text="hi")], [], system="be brief")
    assert "tools" not in captured
    assert captured["system"] == "be brief"
    assert captured["max_tokens"] == 16000
    assert captured["betas"] == ["server-side-fallback-2026-07-01"]
    assert captured["extra_body"] == {"fallbacks": "default"}
    assert r.message.text == "hi"


def test_complete_skips_fallbacks_for_other_models():
    captured: dict = {}
    AnthropicModel(model="claude-sonnet-5", client=_fake_client(captured)).complete(
        [Message(role="user", text="hi")], [ADD]
    )
    assert "betas" not in captured and "extra_body" not in captured
    assert captured["tools"][0]["name"] == "add"
    assert "system" not in captured
