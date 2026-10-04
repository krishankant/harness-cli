"""Build a tool's JSON Schema from a plain Python function, so a tool is one decorator
and no hand-written schema (week 3)."""

from __future__ import annotations

import inspect
import types
from typing import Any, Callable, Iterable, Literal, Union, get_args, get_origin, get_type_hints

from harnessy.types import Tool, ToolSpec

_SIMPLE = {str: "string", int: "integer", float: "number", bool: "boolean"}


# --- Given -----------------------------------------------------------------------------


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into (description, {parameter: description}).
    The description is the first paragraph; parameters come from the `Args:` section."""
    if not doc:
        return "", {}
    lines = inspect.cleandoc(doc).splitlines()
    desc: list[str] = []
    for line in lines:
        if not line.strip() or line.strip() == "Args:":
            break
        desc.append(line.strip())
    params: dict[str, str] = {}
    current: str | None = None
    in_args = False
    for line in lines:
        if line.strip() == "Args:":
            in_args = True
            continue
        if not in_args:
            continue
        if line and not line[0].isspace():
            break  # the next section (Returns:, Raises:, ...)
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 4 and ":" in stripped:
            name, _, text = stripped.partition(":")
            current = name.split("(")[0].strip()
            params[current] = text.strip()
        elif current:
            params[current] = f"{params[current]} {stripped}".strip()
    return " ".join(desc), params


def tool(
    fn: Callable[..., object] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    timeout_s: float | None = None,
    max_chars: int | None = None,
    tags: Iterable[str] = (),
):
    """Turn a function into a Tool. Use it bare (@tool) or with options (@tool(timeout_s=5)).
    The name defaults to the function's name and the description to its docstring."""

    def build(f: Callable[..., object]) -> Tool:
        doc_description, _ = parse_docstring(f.__doc__)
        tool_name = name or f.__name__
        spec = ToolSpec(tool_name, description or doc_description or tool_name, schema_from_function(f))
        return Tool(spec, f, timeout_s, max_chars, frozenset(tags))

    return build(fn) if fn is not None else build


# --- Week 3 exercise -------------------------------------------------------------------


def json_type(annotation: Any) -> dict[str, Any]:
    """The JSON Schema for one parameter's type annotation.

    str -> {"type": "string"}, int -> "integer", float -> "number", bool -> "boolean".
    list[X] -> {"type": "array", "items": json_type(X)}; a bare `list` -> {"type": "array"}.
    Literal["a", "b"] -> {"type": "string", "enum": ["a", "b"]} (the type comes from the
    values, which must all be one simple type).
    X | None and Optional[X] -> json_type(X).
    Anything else -> raise TypeError naming the annotation.
    Hint: typing.get_origin and typing.get_args take annotations apart; `X | None` has
    origin types.UnionType and Optional[X] has origin typing.Union.
    """
    if annotation in _SIMPLE:
        return {"type": _SIMPLE[annotation]}
    if annotation is list:
        return {"type": "array"}
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is list:
        return {"type": "array", "items": json_type(args[0])} if args else {"type": "array"}
    if origin is Literal:
        kinds = {type(a) for a in args}
        if len(kinds) == 1 and next(iter(kinds)) in _SIMPLE:
            return {"type": _SIMPLE[kinds.pop()], "enum": list(args)}
    if origin in (Union, types.UnionType):
        rest = [a for a in args if a is not type(None)]
        if len(rest) == 1 and len(args) == 2:
            return json_type(rest[0])
    raise TypeError(f"Unsupported parameter type for a tool: {annotation!r}")


def schema_from_function(fn: Callable[..., object]) -> dict[str, Any]:
    """The JSON Schema object for fn's parameters.

    Use inspect.signature(fn) for the parameters and typing.get_type_hints(fn) for their
    types (it resolves string annotations). For each parameter:
    - no type hint -> raise TypeError naming the parameter in quotes ('x');
    - *args or **kwargs -> raise TypeError naming the parameter;
    - its schema is json_type(hint), plus "description" if the docstring's Args: section
      describes it (parse_docstring);
    - it is required if it has no default.
    Return {"type": "object", "properties": {...}, "required": [...],
            "additionalProperties": False}, properties in signature order.
    """
    _, arg_docs = parse_docstring(fn.__doc__)
    hints = get_type_hints(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in inspect.signature(fn).parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(f"Tool functions can't take *args or **kwargs: '{pname}' in {fn.__name__}")
        if pname not in hints:
            raise TypeError(f"Parameter '{pname}' of {fn.__name__} needs a type annotation")
        prop = json_type(hints[pname])
        if pname in arg_docs:
            prop["description"] = arg_docs[pname]
        properties[pname] = prop
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
