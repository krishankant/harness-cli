import os
import subprocess
import sys
import textwrap
import time

from harnessy.tools.registry import ToolRegistry, truncate, validate_args
from harnessy.tools.schema import tool
from harnessy.types import Tool, ToolCall, ToolSpec

SCHEMA = {
    "type": "object",
    "properties": {
        "n": {"type": "integer"},
        "x": {"type": "number"},
        "flag": {"type": "boolean"},
        "mode": {"type": "string", "enum": ["a", "b"]},
        "ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["n"],
    "additionalProperties": False,
}
OPEN_SCHEMA = {k: v for k, v in SCHEMA.items() if k != "additionalProperties"}


def test_valid_args_have_no_problems():
    assert validate_args(SCHEMA, {"n": 1, "x": 2.5, "flag": True, "mode": "a", "ids": [1, 2]}) == []


def test_missing_required():
    assert validate_args(SCHEMA, {}) == ["missing required parameter 'n'"]


def test_unknown_param_only_when_additional_properties_false():
    assert validate_args(SCHEMA, {"n": 1, "zz": 2}) == ["unknown parameter 'zz'"]
    assert validate_args(OPEN_SCHEMA, {"n": 1, "zz": 2}) == []


def test_wrong_type_names_the_parameter_and_value():
    [problem] = validate_args(SCHEMA, {"n": "3"})
    assert "'n' must be integer" in problem and "'3'" in problem


def test_bool_is_not_a_number():
    assert len(validate_args(SCHEMA, {"n": True})) == 1
    assert len(validate_args(SCHEMA, {"n": 1, "x": False})) == 1


def test_int_is_a_valid_number():
    assert validate_args(SCHEMA, {"n": 1, "x": 3}) == []


def test_enum():
    [problem] = validate_args(SCHEMA, {"n": 1, "mode": "c"})
    assert "'mode' must be one of" in problem


def test_array_items():
    [problem] = validate_args(SCHEMA, {"n": 1, "ids": [1, "2"]})
    assert "'ids[1]'" in problem


def test_invalid_json_marker():
    [problem] = validate_args(SCHEMA, {"_raw": "{n: 1"})
    assert "not valid JSON" in problem


def test_truncate():
    assert truncate("abc", 5) == "abc"
    assert truncate("x" * 5000, 4000) == "x" * 4000 + "\n[truncated: showing the first 4,000 of 5,000 characters]"


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@tool(timeout_s=0.05)
def slow() -> str:
    """Take too long."""
    time.sleep(0.5)
    return "done"


def call(reg: ToolRegistry, name: str, **args) -> object:
    return reg.call(ToolCall("c1", name, args))


def test_success_is_stringified():
    r = call(ToolRegistry([add]), "add", a=2, b=3)
    assert (r.tool_call_id, r.content, r.is_error) == ("c1", "5", False)


def test_unknown_tool_lists_available_tools():
    r = call(ToolRegistry([add]), "sub")
    assert r.is_error and "'sub'" in r.content and "add" in r.content


def test_invalid_args_name_the_problem_and_the_expected_parameters():
    r = call(ToolRegistry([add]), "add", a="x", b=1)
    assert r.is_error
    assert "Invalid arguments for 'add'" in r.content and "'a' must be integer" in r.content
    assert "a: integer, b: integer" in r.content


def test_exception_becomes_an_error_result():
    @tool
    def boom() -> str:
        """Fail."""
        raise ValueError("disk full")

    r = call(ToolRegistry([boom]), "boom")
    assert r.is_error and "ValueError: disk full" in r.content


def test_type_error_from_a_hand_written_spec():
    t = Tool(ToolSpec("add", "Add.", {"type": "object", "properties": {}}), lambda a, b: a + b)
    r = call(ToolRegistry([t]), "add", a=1)
    assert r.is_error and "Bad arguments for 'add'" in r.content


def test_timeout_uses_the_tool_setting():
    start = time.monotonic()
    r = call(ToolRegistry([slow]), "slow")
    assert r.is_error and "timed out after 0.05s" in r.content
    assert time.monotonic() - start < 0.4


def test_timeout_falls_back_to_the_registry_default():
    lazy = tool(lambda: time.sleep(0.5) or "done", name="lazy")
    r = call(ToolRegistry([lazy], default_timeout_s=0.05), "lazy")
    assert r.is_error and "timed out" in r.content


def test_output_is_truncated_to_the_tool_or_default_limit():
    big = tool(lambda: "y" * 50, name="big", max_chars=10)
    assert "first 10 of 50" in call(ToolRegistry([big]), "big").content
    big2 = tool(lambda: "y" * 50, name="big2")
    assert "first 20 of 50" in call(ToolRegistry([big2], default_max_chars=20), "big2").content


def test_specs_keep_registration_order():
    assert [s.name for s in ToolRegistry([slow, add]).specs()] == ["slow", "add"]


def test_a_hung_tool_does_not_keep_the_process_alive(tmp_path):
    code = textwrap.dedent(
        """
        import time
        from harnessy.tools.registry import ToolRegistry
        from harnessy.types import Tool, ToolCall, ToolSpec
        hang = Tool(ToolSpec("hang", "Hang.", {"type": "object", "properties": {}}), lambda: time.sleep(60), timeout_s=0.1)
        print(ToolRegistry([hang]).call(ToolCall("c1", "hang", {})).content)
        """
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    start = time.monotonic()
    # cwd=tmp_path: `python -c` puts the cwd first on sys.path, which would shadow the tree under test
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env, cwd=tmp_path)
    assert "timed out" in out.stdout, out.stderr
    assert time.monotonic() - start < 10


def test_null_for_an_optional_parameter_is_accepted():
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}, "n": {"type": "integer"}},
        "required": ["q"],
        "additionalProperties": False,
    }
    assert validate_args(schema, {"q": "x", "n": None}) == []
    assert validate_args(schema, {"q": None}) == ["'q' must be string, got NoneType None"]


def test_null_optional_arguments_are_dropped_so_defaults_apply():
    @tool
    def page(q: str, n: int = 5) -> str:
        """Show a page of results."""
        return f"{q}:{n}"

    assert call(ToolRegistry([page]), "page", q="x", n=None).content == "x:5"
