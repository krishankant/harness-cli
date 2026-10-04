import dataclasses

import pytest

from harnessy.types import Message, ModelResponse, ToolCall, Usage


def test_usage_total_and_addition():
    u = Usage(10, 5) + Usage(1, 2)
    assert (u.input_tokens, u.output_tokens, u.total) == (11, 7, 18)


def test_usage_defaults_to_zero():
    assert Usage().total == 0


def test_message_is_frozen():
    m = Message(role="user", text="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.text = "changed"


def test_model_response_holds_message():
    call = ToolCall(id="c1", name="add", arguments={"a": 1})
    r = ModelResponse(message=Message(role="assistant", tool_calls=(call,)), stop_reason="tool_use", usage=Usage())
    assert r.message.tool_calls[0].name == "add"
    assert r.raw is None
