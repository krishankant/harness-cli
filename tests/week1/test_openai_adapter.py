import json
from types import SimpleNamespace

import pytest

from harnessy.models.openai import (
    OpenAIModel,
    from_openai_response,
    map_openai_finish_reason,
    to_openai_messages,
    to_openai_tools,
)
from harnessy.types import Message, ProviderRaw, ToolCall, ToolResult, ToolSpec

ADD = ToolSpec("add", "Add two integers.", {"type": "object", "properties": {"a": {"type": "integer"}}})


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("stop", "end_turn"),
        ("tool_calls", "tool_use"),
        ("length", "max_tokens"),
        ("content_filter", "refused"),
        ("function_call", "error"),
        (None, "error"),
    ],
)
def test_map_finish_reason(reason, expected):
    assert map_openai_finish_reason(reason) == expected


def test_tools_are_wrapped_as_functions():
    assert to_openai_tools([ADD]) == [
        {"type": "function", "function": {"name": "add", "description": "Add two integers.", "parameters": ADD.parameters}}
    ]


def test_system_prompt_becomes_first_message():
    out = to_openai_messages([Message(role="user", text="hi")], system="be brief")
    assert out == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]


def test_no_system_message_when_system_is_none():
    assert to_openai_messages([Message(role="user", text="hi")]) == [{"role": "user", "content": "hi"}]


def test_assistant_tool_calls_have_json_string_arguments():
    m = Message(role="assistant", tool_calls=(ToolCall("call_1", "add", {"a": 17, "b": 25}),))
    [out] = to_openai_messages([m])
    assert out["role"] == "assistant"
    assert out["content"] is None
    [tc] = out["tool_calls"]
    assert tc["id"] == "call_1" and tc["type"] == "function"
    assert tc["function"]["name"] == "add"
    assert json.loads(tc["function"]["arguments"]) == {"a": 17, "b": 25}


def test_assistant_text_only_has_no_tool_calls_key():
    assert to_openai_messages([Message(role="assistant", text="done")]) == [{"role": "assistant", "content": "done"}]


def test_empty_assistant_turn_gets_empty_string_content():
    assert to_openai_messages([Message(role="assistant")]) == [{"role": "assistant", "content": ""}]


def test_each_tool_result_is_its_own_tool_message_with_error_prefix():
    m = Message(role="user", tool_results=(ToolResult("call_1", "42"), ToolResult("call_2", "boom", is_error=True)))
    assert to_openai_messages([m]) == [
        {"role": "tool", "tool_call_id": "call_1", "content": "42"},
        {"role": "tool", "tool_call_id": "call_2", "content": "ERROR: boom"},
    ]


def test_anthropic_raw_is_ignored_and_turn_rebuilt(load_fixture):
    content = load_fixture("anthropic_tool_use.json")["content"]
    m = Message(
        role="assistant",
        text="Let me add those.",
        tool_calls=(ToolCall("toolu_01", "add", {"a": 17, "b": 25}),),
        raw=ProviderRaw("anthropic", content),
    )
    [out] = to_openai_messages([m])
    assert out["content"] == "Let me add those."
    assert out["tool_calls"][0]["id"] == "toolu_01"
    assert "thinking" not in json.dumps(out)


def test_parse_tool_calls(load_fixture):
    resp = load_fixture("openai_tool_calls.json")
    r = from_openai_response(resp)
    assert r.stop_reason == "tool_use"
    assert r.message.text == ""
    assert r.message.tool_calls == (
        ToolCall("call_1", "add", {"a": 17, "b": 25}),
        ToolCall("call_2", "get_time", {}),
    )
    assert r.message.raw == ProviderRaw("openai", resp["choices"][0]["message"])
    assert (r.usage.input_tokens, r.usage.output_tokens) == (80, 30)
    assert r.raw == resp


def test_parse_text_reply(load_fixture):
    r = from_openai_response(load_fixture("openai_stop.json"))
    assert (r.message.text, r.stop_reason, r.message.tool_calls) == ("17 + 25 = 42.", "end_turn", ())


def test_bad_or_non_object_arguments_are_kept_raw(load_fixture):
    r = from_openai_response(load_fixture("openai_bad_args.json"))
    assert r.message.tool_calls[0].arguments == {"_raw": '{"a": 17,'}
    assert r.message.tool_calls[1].arguments == {"_raw": "[1, 2]"}


def _fake_client(captured: dict):
    reply = SimpleNamespace(
        model_dump=lambda **kw: {
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
    )

    def create(**kwargs):
        captured.update(kwargs)
        return reply

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_complete_omits_empty_tools():
    captured: dict = {}
    r = OpenAIModel(model="example-model", client=_fake_client(captured)).complete([Message(role="user", text="hi")], [])
    assert "tools" not in captured
    assert captured["model"] == "example-model"
    assert r.message.text == "hi"


def test_complete_sends_tools_when_present():
    captured: dict = {}
    OpenAIModel(model="example-model", client=_fake_client(captured)).complete([Message(role="user", text="hi")], [ADD])
    assert captured["tools"][0]["function"]["name"] == "add"


def test_missing_model_name_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        OpenAIModel(client=object())
