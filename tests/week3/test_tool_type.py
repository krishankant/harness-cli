from harnessy import loop, types
from harnessy.types import Tool, ToolSpec


def test_tool_lives_in_types_and_loop_reexports_it():
    assert loop.Tool is types.Tool


def test_tool_limits_default_to_none():
    t = Tool(ToolSpec("x", "d", {"type": "object", "properties": {}}), lambda: "ok")
    assert (t.name, t.timeout_s, t.max_chars) == ("x", None, None)
