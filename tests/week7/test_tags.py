from harnessy.memory import MemoryStore, memory_tools
from harnessy.models.scripted import ScriptedModel
from harnessy.subagents import subagent_tool
from harnessy.tools.files import file_tools
from harnessy.tools.schema import tool
from harnessy.tools.web import http_get
from harnessy.types import Tool, ToolSpec


def test_tags_default_to_empty_and_tool_passes_them_on():
    assert Tool(ToolSpec("x", "d", {"type": "object", "properties": {}}), lambda: "").tags == frozenset()
    tagged = tool(lambda: "", name="t", tags={"private_data"})
    assert tagged.tags == frozenset({"private_data"})


def test_the_given_tools_are_tagged(tmp_path):
    read_file, write_file = file_tools(tmp_path)
    remember, recall = memory_tools(MemoryStore(tmp_path / "m.json"))
    assert (read_file.tags, write_file.tags) == (frozenset({"private_data"}), frozenset())
    assert (remember.tags, recall.tags) == (frozenset(), frozenset({"private_data"}))
    assert http_get.tags == frozenset({"untrusted_input", "external_send"})


def test_subagent_carries_its_tools_tags(tmp_path):
    spawn = subagent_tool(ScriptedModel([]), [*file_tools(tmp_path), http_get])
    assert spawn.tags == frozenset({"private_data", "untrusted_input", "external_send"})
