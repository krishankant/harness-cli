"""Week 3 "done when": tools come from @tool, and the loop runs them through ToolRegistry."""

import time

from harnessy.loop import Agent
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.tools.schema import tool
from harnessy.types import ToolCall


@tool
def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: The first number.
        b: The second number.
    """
    return a + b


def test_bad_arguments_get_a_readable_error_and_the_model_fixes_the_call():
    model = ScriptedModel(
        [
            tool_reply(ToolCall("c1", "add", {"a": "seventeen", "b": 25})),
            tool_reply(ToolCall("c2", "add", {"a": 17, "b": 25})),
            text_reply("42"),
        ]
    )
    r = Agent(model, tools=[add]).run("What is 17 + 25?")
    first = r.messages[2].tool_results[0]
    assert first.is_error and "'a' must be integer" in first.content and "a: integer, b: integer" in first.content
    second = r.messages[4].tool_results[0]
    assert (second.content, second.is_error) == ("42", False)
    assert (r.stop_reason, r.final_text) == ("end_turn", "42")


def test_agent_sends_the_generated_schema():
    model = ScriptedModel([text_reply("hi")])
    Agent(model, tools=[add]).run("x")
    [spec] = model.calls[0].tools
    assert spec.description == "Add two integers."
    assert spec.parameters["additionalProperties"] is False
    assert spec.parameters["properties"]["a"]["description"] == "The first number."


def test_agent_truncates_large_tool_output():
    big = tool(lambda: "x" * 10_000, name="big")
    model = ScriptedModel([tool_reply(ToolCall("c1", "big", {})), text_reply("ok")])
    [res] = Agent(model, tools=[big]).run("x").messages[2].tool_results
    assert res.content.endswith("[truncated: showing the first 4,000 of 10,000 characters]")


def test_agent_times_out_a_slow_tool():
    slow = tool(lambda: time.sleep(0.5) or "done", name="slow", timeout_s=0.05)
    model = ScriptedModel([tool_reply(ToolCall("c1", "slow", {})), text_reply("ok")])
    [res] = Agent(model, tools=[slow]).run("x").messages[2].tool_results
    assert res.is_error and "timed out" in res.content
