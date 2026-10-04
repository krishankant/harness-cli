"""Week 5: the loop writes a trace."""

from harnessy.loop import Agent
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.tools.schema import tool
from harnessy.tracer import Tracer, load_trace
from harnessy.types import ToolCall


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def test_a_run_writes_its_events_in_order(tmp_path):
    model = ScriptedModel(
        [tool_reply(ToolCall("c1", "add", {"a": 2, "b": 2}), input_tokens=100, output_tokens=20), text_reply("4", 130, 5)]
    )
    path = tmp_path / "t.jsonl"
    Agent(model, tools=[add], system="sys", tracer=Tracer(path)).run("What is 2+2?")
    events = load_trace(path)
    assert [e["kind"] for e in events] == ["run_start", "model_call", "tool_result", "model_call", "stop"]
    start, call, result, final, stop = events
    assert (start["task"], start["model"], start["system"], start["tools"]) == ("What is 2+2?", "scripted", "sys", ["add"])
    assert (call["step"], call["stop_reason"], call["input_tokens"], call["output_tokens"]) == (0, "tool_use", 100, 20)
    assert call["tool_calls"] == [{"id": "c1", "name": "add", "arguments": {"a": 2, "b": 2}}]
    assert (result["step"], result["name"], result["tool_call_id"], result["content"], result["is_error"]) == (0, "add", "c1", "4", False)
    assert result["arguments"] == {"a": 2, "b": 2}
    assert (final["step"], final["text"]) == (1, "4")
    assert (stop["stop_reason"], stop["steps"], stop["input_tokens"], stop["output_tokens"], stop["error"], stop["final_text"]) == (
        "end_turn", 2, 230, 25, None, "4"
    )


def test_every_exit_path_writes_a_stop_event(tmp_path):
    cases = {
        "max_steps": (ScriptedModel([tool_reply(ToolCall("c1", "add", {"a": 1, "b": 1}))]), {"max_steps": 1}),
        "model_error": (ScriptedModel([RuntimeError("503")]), {}),
        "refused": (ScriptedModel([text_reply("", stop_reason="refused")]), {}),
        "max_tokens": (ScriptedModel([tool_reply(ToolCall("c1", "add", {"a": 1, "b": 1}), input_tokens=500)]), {"max_tokens_total": 100}),
    }
    for reason, (model, limits) in cases.items():
        path = tmp_path / f"{reason}.jsonl"
        r = Agent(model, tools=[add], tracer=Tracer(path), **limits).run("x")
        stop = load_trace(path)[-1]
        assert (r.stop_reason, stop["kind"], stop["stop_reason"]) == (reason, "stop", reason), reason


def test_without_a_tracer_nothing_is_written(tmp_path):
    Agent(ScriptedModel([text_reply("hi")])).run("x")
    assert list(tmp_path.iterdir()) == []
