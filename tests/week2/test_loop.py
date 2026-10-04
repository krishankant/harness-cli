from harnessy.loop import Agent, RunResult, Tool
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.types import ToolCall, ToolSpec


def spec(name: str) -> ToolSpec:
    return ToolSpec(name, f"The {name} tool.", {"type": "object", "properties": {}})


def add(a: int, b: int) -> str:
    return str(a + b)


ADD = Tool(spec("add"), add)
TIME = Tool(spec("get_time"), lambda: "12:00")


class FakeClock:
    def __init__(self, step: float):
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def test_plain_answer_ends_turn():
    model = ScriptedModel([text_reply("hello")])
    r = Agent(model).run("hi")
    assert isinstance(r, RunResult)
    assert (r.final_text, r.stop_reason, len(r.steps)) == ("hello", "end_turn", 1)
    assert [m.role for m in r.messages] == ["user", "assistant"]
    assert r.messages[0].text == "hi"


def test_tool_calls_run_in_order_and_results_go_back_together():
    model = ScriptedModel(
        [
            tool_reply(ToolCall("c1", "add", {"a": 17, "b": 25}), ToolCall("c2", "get_time", {})),
            text_reply("42, and it is 12:00"),
        ]
    )
    r = Agent(model, tools=[ADD, TIME], system="sys").run("sum and time?")
    assert r.stop_reason == "end_turn" and r.final_text == "42, and it is 12:00"
    results = r.messages[2].tool_results
    assert [(x.tool_call_id, x.content, x.is_error) for x in results] == [("c1", "42", False), ("c2", "12:00", False)]
    assert r.messages[2].role == "user"
    assert r.steps[0].tool_results == results
    second_call = model.calls[1]
    assert second_call.system == "sys"
    assert [t.name for t in second_call.tools] == ["add", "get_time"]
    assert len(second_call.messages) == 3


def test_usage_is_summed_across_steps():
    model = ScriptedModel([tool_reply(ToolCall("c1", "get_time", {}), input_tokens=100, output_tokens=20), text_reply("ok", 150, 10)])
    r = Agent(model, tools=[TIME]).run("t")
    assert (r.usage.input_tokens, r.usage.output_tokens) == (250, 30)


def test_unknown_tool_is_an_error_result():
    model = ScriptedModel([tool_reply(ToolCall("c1", "nope", {})), text_reply("sorry")])
    r = Agent(model, tools=[ADD]).run("x")
    [res] = r.messages[2].tool_results
    assert res.is_error and "nope" in res.content and "add" in res.content


def test_bad_arguments_are_an_error_result():
    model = ScriptedModel([tool_reply(ToolCall("c1", "add", {"a": 1})), text_reply("retrying")])
    [res] = Agent(model, tools=[ADD]).run("x").messages[2].tool_results
    assert res.is_error and "add" in res.content


def test_tool_exception_is_an_error_result():
    def boom() -> str:
        raise ValueError("disk full")

    model = ScriptedModel([tool_reply(ToolCall("c1", "boom", {})), text_reply("ok")])
    [res] = Agent(model, tools=[Tool(spec("boom"), boom)]).run("x").messages[2].tool_results
    assert res.is_error and "disk full" in res.content


def test_non_string_tool_output_is_stringified():
    model = ScriptedModel([tool_reply(ToolCall("c1", "n", {})), text_reply("ok")])
    [res] = Agent(model, tools=[Tool(spec("n"), lambda: 42)]).run("x").messages[2].tool_results
    assert (res.content, res.is_error) == ("42", False)


def test_max_steps_stops_a_model_that_never_finishes():
    model = ScriptedModel([tool_reply(ToolCall(f"c{i}", "get_time", {})) for i in range(10)])
    r = Agent(model, tools=[TIME], max_steps=3).run("loop forever")
    assert r.stop_reason == "max_steps"
    assert len(model.calls) == 3 and len(r.steps) == 3


def test_token_budget_stops_before_the_next_call():
    model = ScriptedModel([tool_reply(ToolCall(f"c{i}", "get_time", {}), input_tokens=60, output_tokens=0) for i in range(5)])
    r = Agent(model, tools=[TIME], max_tokens_total=100).run("x")
    assert r.stop_reason == "max_tokens"
    assert len(model.calls) == 2


def test_timeout_uses_the_injected_clock():
    model = ScriptedModel([tool_reply(ToolCall(f"c{i}", "get_time", {})) for i in range(5)])
    r = Agent(model, tools=[TIME], timeout_s=10, clock=FakeClock(step=4)).run("x")
    assert r.stop_reason == "timeout"
    assert len(model.calls) == 2


def test_model_exception_becomes_model_error():
    r = Agent(ScriptedModel([RuntimeError("503 overloaded")])).run("x")
    assert r.stop_reason == "model_error" and "503 overloaded" in r.error


def test_refusal_stops_with_refused():
    r = Agent(ScriptedModel([text_reply("", stop_reason="refused")])).run("x")
    assert r.stop_reason == "refused"


def test_truncated_tool_call_is_not_run():
    calls = []
    tool = Tool(spec("get_time"), lambda: calls.append(1) or "12:00")
    model = ScriptedModel([tool_reply(ToolCall("c1", "get_time", {}), stop_reason="max_tokens")])
    r = Agent(model, tools=[tool]).run("x")
    assert r.stop_reason == "model_error" and calls == []


def test_verbose_prints_each_step():
    lines: list[str] = []
    model = ScriptedModel([tool_reply(ToolCall("c1", "get_time", {})), text_reply("done")])
    Agent(model, tools=[TIME], verbose=True, printer=lines.append).run("x")
    assert any("step 0" in line for line in lines) and any("step 1" in line for line in lines)


def test_error_stop_reason_is_model_error():
    r = Agent(ScriptedModel([text_reply("", stop_reason="error")])).run("x")
    assert r.stop_reason == "model_error" and r.error


def test_tool_calls_are_not_run_when_the_reply_errored_or_refused():
    for stop, expected in [("error", "model_error"), ("refused", "refused")]:
        calls = []
        tool = Tool(spec("get_time"), lambda: calls.append(1) or "12:00")
        model = ScriptedModel([tool_reply(ToolCall("c1", "get_time", {}), stop_reason=stop)])
        r = Agent(model, tools=[tool]).run("x")
        assert (r.stop_reason, calls) == (expected, []), stop
