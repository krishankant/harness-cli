"""Week 6 "done when": hooks run through the loop."""

from harnessy.approvals import ApprovalHook
from harnessy.hooks import Block, Hook, StopCheck
from harnessy.loop import Agent
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.subagents import subagent_tool
from harnessy.todo import TodoList
from harnessy.tools.files import file_tools
from harnessy.tracer import Tracer, load_trace
from harnessy.types import ToolCall

WRITE = ToolCall("c1", "write_file", {"path": "a.txt", "content": "hi"})


def test_a_risky_tool_waits_for_approval_and_the_run_continues(tmp_path):
    asked = []
    hook = ApprovalHook({"write_file": "ask"}, approver=lambda call: asked.append(call.name) or True)
    model = ScriptedModel([tool_reply(WRITE), text_reply("saved")])
    r = Agent(model, tools=file_tools(tmp_path), hooks=[hook]).run("save hi")
    assert asked == ["write_file"] and (tmp_path / "a.txt").read_text() == "hi" and r.stop_reason == "end_turn"


def test_a_declined_call_becomes_an_error_result(tmp_path):
    hook = ApprovalHook({"write_file": "ask"}, approver=lambda call: False)
    model = ScriptedModel([tool_reply(WRITE), text_reply("ok, I won't")])
    r = Agent(model, tools=file_tools(tmp_path), hooks=[hook]).run("save hi")
    [res] = r.messages[2].tool_results
    assert res.is_error and "declined" in res.content and res.tool_call_id == "c1"
    assert not (tmp_path / "a.txt").exists() and r.stop_reason == "end_turn"


def test_two_subagents_and_the_parent_sees_only_their_answers(tmp_path):
    (tmp_path / "a.txt").write_text("alpha facts")
    (tmp_path / "b.txt").write_text("beta facts")
    model = ScriptedModel(
        [
            tool_reply(
                ToolCall("p1", "spawn_subagent", {"task": "Summarize a.txt", "tools": ["read_file"]}),
                ToolCall("p2", "spawn_subagent", {"task": "Summarize b.txt", "tools": ["read_file"]}),
            ),
            tool_reply(ToolCall("k1", "read_file", {"path": "a.txt"})),
            text_reply("A is about alpha."),
            tool_reply(ToolCall("k2", "read_file", {"path": "b.txt"})),
            text_reply("B is about beta."),
            text_reply("A: alpha. B: beta."),
        ]
    )
    parent = Agent(model, tools=[subagent_tool(model, file_tools(tmp_path))])
    r = parent.run("Compare a.txt and b.txt, one helper per file.")
    assert [x.content for x in r.messages[2].tool_results] == ["A is about alpha.", "B is about beta."]
    assert not any("facts" in res.content for m in r.messages for res in m.tool_results)
    assert (r.final_text, len(r.messages)) == ("A: alpha. B: beta.", 4)
    assert model.calls[1].messages[0].text == "Summarize a.txt" and len(model.calls[1].messages) == 1


def test_an_on_stop_rejection_sends_the_agent_back_once():
    check = StopCheck(lambda result: None if "checked" in result.final_text else "Run the check before you finish.")
    model = ScriptedModel([text_reply("done"), text_reply("checked, done")])
    r = Agent(model, hooks=[check]).run("x")
    assert (r.stop_reason, r.final_text, len(model.calls)) == ("end_turn", "checked, done", 2)
    assert model.calls[1].messages[-1].text == "Run the check before you finish."


def test_a_blocking_before_model_hook_stops_the_run():
    class Gate(Hook):
        def before_model(self, view):
            return Block("maintenance window")

    r = Agent(ScriptedModel([]), hooks=[Gate()]).run("x")
    assert (r.stop_reason, r.error) == ("blocked", "maintenance window")


def test_the_tracer_still_works_through_trace_hook(tmp_path):
    hook = ApprovalHook({"write_file": "deny"})
    model = ScriptedModel([tool_reply(WRITE), text_reply("ok")])
    path = tmp_path / "t.jsonl"
    Agent(model, tools=file_tools(tmp_path), hooks=[hook], tracer=Tracer(path)).run("save hi")
    events = load_trace(path)
    assert [e["kind"] for e in events] == ["run_start", "model_call", "tool_result", "model_call", "stop"]
    assert events[2]["is_error"] and "not allowed" in events[2]["content"] and events[3]["step"] == 1


def test_the_todo_list_reaches_the_model_but_not_the_history():
    todo = TodoList()
    model = ScriptedModel([tool_reply(ToolCall("c1", "todo", {"action": "add", "text": "read the notes", "id": None})), text_reply("ok")])
    r = Agent(model, tools=[todo.tool()], hooks=[todo]).run("plan it")
    assert model.calls[1].messages[-1].text == "Todo list:\n[ ] #1 read the notes"
    assert all("Todo list" not in m.text for m in r.messages)
