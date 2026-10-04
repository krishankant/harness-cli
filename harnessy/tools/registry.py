"""The tool registry: check a call's arguments, run it with a time limit, cap its output,
and turn every failure into a result the model can read (week 3)."""

from __future__ import annotations

import threading
from typing import Any, Iterable

from harnessy.types import Tool, ToolCall, ToolResult, ToolSpec

# JSON Schema type name -> the Python types that satisfy it.
_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


# --- Week 3 exercise -------------------------------------------------------------------


def _type_ok(value: Any, schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind not in _TYPES:
        return True
    if isinstance(value, bool) and kind in ("integer", "number"):
        return False  # bool is a subclass of int in Python, but not in JSON
    return isinstance(value, _TYPES[kind])


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Return the problems with args under schema (a JSON Schema object); [] if none.

    Check only what the schema says, in this order:
    - args == {"_raw": ...} (week 1's marker for invalid JSON) -> return just
      ["the arguments were not valid JSON: <raw!r>. Send a JSON object."]
    - each name in schema["required"] is present: "missing required parameter 'n'"
    - None for a name that is NOT required counts as "not given": no problem (models often
      send null for optional parameters)
    - a name not in schema["properties"] is a problem ONLY if schema["additionalProperties"]
      is False (JSON Schema allows extra names by default): "unknown parameter 'zz'"
    - each known value matches its "type" (use _TYPES): "'n' must be integer, got str '3'".
      bool is NOT an integer or number here, even though Python says it is; an int IS a
      valid number.
    - "enum": "'mode' must be one of ['a', 'b'], got 'c'"
    - "array" with "items": check each item's type: "'ids[1]' must be integer, got str '2'"
    """
    properties = schema.get("properties", {})
    if set(args) == {"_raw"} and "_raw" not in properties:
        return [f"the arguments were not valid JSON: {args['_raw']!r}. Send a JSON object."]
    required = set(schema.get("required", []))
    problems = [f"missing required parameter '{name}'" for name in schema.get("required", []) if name not in args]
    for name, value in args.items():
        if value is None and name not in required:
            continue
        prop = properties.get(name)
        if prop is None:
            if schema.get("additionalProperties") is False:
                problems.append(f"unknown parameter '{name}'")
            continue
        if not _type_ok(value, prop):
            problems.append(f"'{name}' must be {prop['type']}, got {type(value).__name__} {value!r}")
            continue
        if "enum" in prop and value not in prop["enum"]:
            problems.append(f"'{name}' must be one of {prop['enum']}, got {value!r}")
        if prop.get("type") == "array" and "items" in prop:
            for i, item in enumerate(value):
                if not _type_ok(item, prop["items"]):
                    problems.append(
                        f"'{name}[{i}]' must be {prop['items'].get('type')}, got {type(item).__name__} {item!r}"
                    )
    return problems


def truncate(text: str, max_chars: int) -> str:
    """Return text unchanged if it has at most max_chars characters. Otherwise the first
    max_chars characters, then a newline and
    "[truncated: showing the first 4,000 of 51,200 characters]" (numbers with commas)."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[truncated: showing the first {max_chars:,} of {len(text):,} characters]"


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool], default_timeout_s: float = 30.0, default_max_chars: int = 4000):
        self.tools = list(tools)
        self._by_name = {t.name: t for t in self.tools}
        self.default_timeout_s = default_timeout_s
        self.default_max_chars = default_max_chars

    # --- Given ---

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self.tools]

    def expected(self, tool: Tool) -> str:
        """A one-line summary of a tool's parameters, for error messages: "a: integer, b: integer"."""
        props = tool.spec.parameters.get("properties", {})
        required = set(tool.spec.parameters.get("required", []))
        parts = [f"{n}: {p.get('type', 'any')}{'' if n in required else ' (optional)'}" for n, p in props.items()]
        return ", ".join(parts) or "none"

    # --- Week 3 exercise ---

    def call(self, call: ToolCall) -> ToolResult:
        """Run one call and ALWAYS return a ToolResult with tool_call_id=call.id. Never raise.

        1. Unknown name -> error: "Unknown tool 'x'. Available tools: a, b."
        2. validate_args problems -> error:
           "Invalid arguments for 'add': <problems joined by '; '>. Expected parameters: <self.expected(tool)>."
        2b. Drop arguments whose value is None and whose name isn't required, so the
            function's own default applies.
        3. Run tool.fn(**arguments) in a threading.Thread(daemon=True) and join it for
           at most the tool's timeout_s (or self.default_timeout_s if None). Still alive ->
           error "Tool 'x' timed out after 0.05s. ..." (format the number with :g). Python
           can't kill a thread, so it keeps running in the background; daemon=True means it
           won't stop your program from exiting (a ThreadPoolExecutor worker would). Week 7
           moves risky tools into a subprocess that can be killed.
           Catch the tool's exception inside the thread and hand it back (e.g. in a dict).
        4. TypeError -> error "Bad arguments for 'x': <e>. Expected parameters: ...";
           any other exception -> error "Tool 'x' failed: <ExceptionType>: <e>".
        5. Success -> str() the output if it isn't a str, then truncate it to the tool's
           max_chars (or self.default_max_chars).
        """
        tool = self._by_name.get(call.name)
        if tool is None:
            available = ", ".join(sorted(self._by_name)) or "none"
            return ToolResult(call.id, f"Unknown tool '{call.name}'. Available tools: {available}.", is_error=True)
        problems = validate_args(tool.spec.parameters, call.arguments)
        if problems:
            return ToolResult(
                call.id,
                f"Invalid arguments for '{call.name}': {'; '.join(problems)}. Expected parameters: {self.expected(tool)}.",
                is_error=True,
            )
        required = set(tool.spec.parameters.get("required", []))
        arguments = {k: v for k, v in call.arguments.items() if not (v is None and k not in required)}
        timeout = tool.timeout_s if tool.timeout_s is not None else self.default_timeout_s
        outcome: dict[str, Any] = {}

        def target() -> None:
            try:
                outcome["output"] = tool.fn(**arguments)
            except Exception as e:
                outcome["error"] = e

        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            return ToolResult(
                call.id, f"Tool '{call.name}' timed out after {timeout:g}s. Try a smaller request.", is_error=True
            )
        error = outcome.get("error")
        if isinstance(error, TypeError):
            return ToolResult(
                call.id, f"Bad arguments for '{call.name}': {error}. Expected parameters: {self.expected(tool)}.", is_error=True
            )
        if error is not None:
            return ToolResult(call.id, f"Tool '{call.name}' failed: {type(error).__name__}: {error}", is_error=True)
        output = outcome["output"]
        max_chars = tool.max_chars if tool.max_chars is not None else self.default_max_chars
        return ToolResult(call.id, truncate(output if isinstance(output, str) else str(output), max_chars))
