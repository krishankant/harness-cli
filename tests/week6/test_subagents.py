import pytest

from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.subagents import SUBAGENT_SYSTEM, subagent_tool
from harnessy.tools.files import file_tools
from harnessy.types import Message, ToolCall


@pytest.fixture
def files(tmp_path):
    (tmp_path / "a.txt").write_text("alpha facts")
    return file_tools(tmp_path)


def test_the_child_gets_a_fresh_context_and_only_the_named_tools(files):
    model = ScriptedModel([tool_reply(ToolCall("k1", "read_file", {"path": "a.txt"})), text_reply("A is about alpha.")])
    spawn = subagent_tool(model, files)
    assert spawn.name == "spawn_subagent" and spawn.spec.parameters["required"] == ["task"]
    assert spawn.fn(task="Summarize a.txt", tools=["read_file"]) == "A is about alpha."
    first = model.calls[0]
    assert first.messages == [Message("user", text="Summarize a.txt")] and first.system == SUBAGENT_SYSTEM
    assert [t.name for t in first.tools] == ["read_file"]


def test_all_tools_by_default(files):
    model = ScriptedModel([text_reply("ok")])
    subagent_tool(model, files).fn(task="t")
    assert [t.name for t in model.calls[0].tools] == ["read_file", "write_file"]


def test_unknown_tool_names_raise(files):
    subagent_tool(ScriptedModel([text_reply("ok")]), files).fn(task="t")  # fails plainly while still a stub
    with pytest.raises(ValueError, match="unknown tools: web. Available: read_file, write_file"):
        subagent_tool(ScriptedModel([]), files).fn(task="t", tools=["web"])


def test_an_early_stop_is_reported(files):
    model = ScriptedModel([tool_reply(ToolCall("k1", "read_file", {"path": "a.txt"}), text="Reading a.txt")])
    out = subagent_tool(model, files, max_steps=1).fn(task="t")
    assert out == "The subagent stopped early (max_steps). Partial answer: "


def test_an_empty_answer(files):
    assert subagent_tool(ScriptedModel([text_reply("")]), files).fn(task="t") == "(the subagent returned no text)"


def test_hooks_passed_to_subagent_tool_apply_to_the_child(tmp_path):
    from harnessy.approvals import ApprovalHook

    files = file_tools(tmp_path)
    model = ScriptedModel([tool_reply(ToolCall("k1", "write_file", {"path": "x.txt", "content": "hi"})), text_reply("done")])
    spawn = subagent_tool(model, files, hooks=[ApprovalHook({"write_file": "deny"})])
    assert spawn.fn(task="write x.txt", tools=["write_file"]) == "done"
    assert not (tmp_path / "x.txt").exists()
