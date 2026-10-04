from typing import Literal, Optional

import pytest

from harnessy.tools.schema import json_type, parse_docstring, schema_from_function, tool
from harnessy.types import Tool


def test_simple_types():
    assert [json_type(t) for t in (str, int, float, bool)] == [
        {"type": "string"},
        {"type": "integer"},
        {"type": "number"},
        {"type": "boolean"},
    ]


def test_list_types():
    assert json_type(list[int]) == {"type": "array", "items": {"type": "integer"}}
    assert json_type(list) == {"type": "array"}


def test_literal_becomes_enum():
    assert json_type(Literal["asc", "desc"]) == {"type": "string", "enum": ["asc", "desc"]}
    assert json_type(Literal[1, 2]) == {"type": "integer", "enum": [1, 2]}


def test_optional_unwraps():
    assert json_type(Optional[int]) == {"type": "integer"}
    assert json_type(str | None) == {"type": "string"}


def test_unsupported_types_raise_naming_the_type():
    with pytest.raises(TypeError, match="dict"):
        json_type(dict)
    with pytest.raises(TypeError):
        json_type(int | str)


def search(query: str, limit: int = 5, order: Literal["asc", "desc"] = "asc", tags: list[str] | None = None) -> str:
    """Search the notes.

    A longer explanation that is not part of the description.

    Args:
        query: Words to look for.
        limit: Maximum results
            to return.
    """
    return query


def test_schema_from_function():
    assert schema_from_function(search) == {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to look for."},
            "limit": {"type": "integer", "description": "Maximum results to return."},
            "order": {"type": "string", "enum": ["asc", "desc"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def test_missing_annotation_raises_naming_the_parameter():
    def f(x):
        return x

    with pytest.raises(TypeError, match="'x'"):
        schema_from_function(f)


def test_star_args_are_rejected():
    def g(*items: int) -> int:
        return 0

    with pytest.raises(TypeError, match="items"):
        schema_from_function(g)


def test_parse_docstring_is_given():
    desc, args = parse_docstring(search.__doc__)
    assert desc == "Search the notes."
    assert args == {"query": "Words to look for.", "limit": "Maximum results to return."}
    assert parse_docstring(None) == ("", {})


def test_tool_decorator_bare_and_with_options():
    t = tool(search)
    assert isinstance(t, Tool) and t.fn is search
    assert (t.name, t.spec.description, t.timeout_s, t.max_chars) == ("search", "Search the notes.", None, None)
    assert t.spec.parameters == schema_from_function(search)
    t2 = tool(name="find", description="Find notes.", timeout_s=2, max_chars=100)(search)
    assert (t2.name, t2.spec.description, t2.timeout_s, t2.max_chars) == ("find", "Find notes.", 2, 100)


def test_tool_without_docstring_uses_its_name():
    assert tool(lambda: "x", name="noop").spec.description == "noop"
