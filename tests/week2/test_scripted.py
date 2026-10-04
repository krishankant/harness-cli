import pytest

from harnessy.models.base import Model
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.types import Message, ToolCall


def test_scripted_model_replays_and_records():
    m = ScriptedModel([text_reply("one"), tool_reply(ToolCall("c1", "add", {}))])
    assert isinstance(m, Model)
    first = m.complete([Message(role="user", text="hi")], [], "sys")
    second = m.complete([], [])
    assert first.message.text == "one" and first.stop_reason == "end_turn"
    assert second.message.tool_calls[0].id == "c1" and second.stop_reason == "tool_use"
    assert m.calls[0].system == "sys" and m.calls[0].messages[0].text == "hi"


def test_scripted_model_raises_queued_exceptions_and_runs_out():
    m = ScriptedModel([RuntimeError("api down")])
    with pytest.raises(RuntimeError, match="api down"):
        m.complete([], [])
    with pytest.raises(RuntimeError, match="ran out"):
        m.complete([], [])
