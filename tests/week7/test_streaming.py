import pytest

from harnessy.loop import Agent
from harnessy.models.anthropic import AnthropicModel
from harnessy.models.openai_stream import merge_openai_chunks
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.streaming import Done, StreamingModel, TextDelta, ToolEnd, ToolStart, collect_stream, stream_agent
from harnessy.tools.schema import tool
from harnessy.types import ModelResponse, ToolCall

CHUNKS = [
    {"id": "c1", "model": "m", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Let me "}}]},
    {"id": "c1", "model": "m", "choices": [{"index": 0, "delta": {"content": "add."}}]},
    {"id": "c1", "model": "m", "choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "type": "function", "function": {"name": "add", "arguments": '{"a": '}}]}}]},
    {"id": "c1", "model": "m", "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "2, "}}]}}]},
    {"id": "c1", "model": "m", "choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 1, "id": "call_2", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]}}]},
    {"id": "c1", "model": "m", "choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"b": 3}'}}]}}]},
    {"id": "c1", "model": "m", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    {"id": "c1", "model": "m", "choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 12}},
]


def test_merge_openai_chunks():
    merged = merge_openai_chunks(CHUNKS)
    assert merged["id"] == "c1" and merged["usage"] == {"prompt_tokens": 50, "completion_tokens": 12}
    [choice] = merged["choices"]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Let me add."
    assert choice["message"]["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "add", "arguments": '{"a": 2, "b": 3}'}},
        {"id": "call_2", "type": "function", "function": {"name": "get_time", "arguments": "{}"}},
    ]


def test_merge_text_only():
    merged = merge_openai_chunks([
        {"id": "c2", "model": "m", "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": "stop"}]},
    ])
    assert merged["choices"][0]["message"] == {"role": "assistant", "content": "Hi"} and merged["usage"] == {}


def test_collect_stream():
    texts = []
    final = text_reply("hello")
    assert collect_stream(iter(["hel", "lo", final]), texts.append) is final and texts == ["hel", "lo"]
    with pytest.raises(RuntimeError, match="without a response"):
        collect_stream(iter(["x"]), texts.append)


def test_scripted_model_streams_in_chunks():
    items = list(ScriptedModel([text_reply("The sum is 5.")]).stream([], []))
    assert items[:-1] == ["The sum ", "is 5."] and isinstance(items[-1], ModelResponse)


def test_streaming_model_falls_back_to_one_chunk():
    class Plain:
        name = "plain"

        def complete(self, messages, tools, system=None):
            return text_reply("all at once")

    texts = []
    assert StreamingModel(Plain(), texts.append).complete([], []).message.text == "all at once"
    assert texts == ["all at once"]


class FakeFinal:
    def __init__(self, data):
        self.data = data

    def model_dump(self, **kwargs):
        return self.data


class FakeStream:
    def __init__(self, texts, final):
        self.text_stream, self._final = iter(texts), final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._final


def test_anthropic_stream_uses_the_sdk_helper(load_fixture):
    seen = {}

    class Messages:
        def stream(self, **kwargs):
            seen.update(kwargs)
            return FakeStream(["Hel", "lo"], FakeFinal(load_fixture("anthropic_end_turn.json")))

    client = type("Client", (), {"beta": type("Beta", (), {"messages": Messages()})()})()
    items = list(AnthropicModel(model="claude-opus-5", client=client).stream([], [], system="s"))
    assert items[:2] == ["Hel", "lo"] and isinstance(items[-1], ModelResponse)
    assert seen["model"] == "claude-opus-5" and seen["system"] == "s" and "tools" not in seen


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def test_stream_agent_yields_events_in_order():
    model = ScriptedModel([tool_reply(ToolCall("c1", "add", {"a": 2, "b": 3}), text="Adding."), text_reply("The sum is 5.")])
    events = list(stream_agent(Agent(model, tools=[add]), "2 + 3?"))
    assert [type(e).__name__ for e in events] == ["TextDelta", "ToolStart", "ToolEnd", "TextDelta", "TextDelta", "Done"]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Adding.The sum is 5."
    assert isinstance(events[1], ToolStart) and events[1].call.name == "add"
    assert isinstance(events[2], ToolEnd) and events[2].result.content == "5"
    assert isinstance(events[-1], Done) and events[-1].result.final_text == "The sum is 5."


def test_stream_agent_reraises_errors_from_the_run():
    from harnessy.hooks import Hook

    class Broken(Hook):
        def before_tool(self, call):
            raise ValueError("hook bug")

    model = ScriptedModel([tool_reply(ToolCall("c1", "add", {"a": 2, "b": 3})), text_reply("ok")])
    list(stream_agent(Agent(ScriptedModel([text_reply("fine")])), "x"))  # fails plainly while a stub
    with pytest.raises(ValueError, match="hook bug"):
        list(stream_agent(Agent(model, tools=[add], hooks=[Broken()]), "x"))


def test_streaming_a_retrying_model_over_a_plain_model_still_sends_text():
    from harnessy.models.retry import RetryingModel

    class Plain:
        name = "plain"

        def complete(self, messages, tools, system=None):
            return text_reply("all at once")

    texts = []
    StreamingModel(RetryingModel(Plain(), sleep=lambda s: None), texts.append).complete([], [])
    assert texts == ["all at once"]
