"""Week 4 "done when": a long run stays under the context budget and still finishes."""

from harnessy.context import ContextManager, estimate_tokens
from harnessy.loop import Agent
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.tools.schema import tool
from harnessy.types import ToolCall


@tool
def read_chunk(n: int) -> str:
    """Read chunk n of the report."""
    return f"chunk {n} " + "c" * 300


def long_run(steps: int = 30) -> ScriptedModel:
    replies = [tool_reply(ToolCall(f"c{i}", "read_chunk", {"n": i}), text="thinking " * 250) for i in range(steps)]
    return ScriptedModel(replies + [text_reply("done")])


def test_a_30_step_run_stays_under_budget_and_finishes():
    model = long_run()
    agent = Agent(model, tools=[read_chunk], system="sys", max_steps=40, context=ContextManager(budget_tokens=8000))
    r = agent.run("Read all 30 chunks.")
    assert (r.stop_reason, len(model.calls)) == ("end_turn", 31)
    assert max(estimate_tokens(c.messages) for c in model.calls) <= 8000
    assert len(r.messages) == 62  # the history keeps every turn...
    assert estimate_tokens(r.messages) > 8000  # ...which would not have fit


def test_system_and_tools_are_identical_on_every_call():
    model = long_run()
    Agent(model, tools=[read_chunk], system="sys", max_steps=40, context=ContextManager(budget_tokens=8000)).run("x")
    assert all(c.system == "sys" and c.tools == model.calls[0].tools for c in model.calls)


def test_without_a_context_manager_the_full_history_is_sent():
    model = long_run(steps=5)
    Agent(model, tools=[read_chunk], max_steps=10).run("x")
    assert len(model.calls[-1].messages) == 11
