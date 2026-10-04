# Week 3: Tools

**Time:** about 5 hours (1.5 reading, 3 building, 30 minutes on notes).

**Before you start:** the week 3 tests run through your `Agent`, so your week 2 loop must pass `uv run pytest tests/week2`.

**You're done when:**

1. `uv run pytest tests/week3` passes (52 tests), and `tests/week2` still passes after you wire the registry in (section 9), and
2. `uv run python -m scripts.week3_demo` writes and reads back a haiku on both providers.

## 1. Read first

| Read | Look for |
| --- | --- |
| [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents) (Anthropic) | Namespacing, returning meaningful context, token-efficient responses, and testing tools with evals. |
| [SWE-agent: Agent-Computer Interfaces](https://arxiv.org/abs/2405.15793) (Yang et al., 2024), sections 2–3 | Changing only the tool interface moved benchmark scores a lot. Note what they changed: line numbers, capped output, errors that say what to do next. |

## 2. Tools are prompts

The model never sees your Python function. It sees three things: a **name**, a **description** and a **JSON Schema** for the parameters. Then, after the call, it sees whatever text you send back. All four are prompts.

This week you stop writing schemas by hand. You write a normal function:

```python
@tool
def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: The first number.
        b: The second number.
    """
    return a + b
```

and `@tool` produces what the model sees:

```json
{"name": "add", "description": "Add two integers.",
 "parameters": {"type": "object",
   "properties": {"a": {"type": "integer", "description": "The first number."},
                  "b": {"type": "integer", "description": "The second number."}},
   "required": ["a", "b"], "additionalProperties": false}}
```

The type hints, the default values and the docstring become the schema. There's one source of truth, and it can't drift from the function.

From your function to what the model sees:

```mermaid
flowchart LR
  F["def add(a: int, b: int) -> int<br/>docstring + type hints"] --> D["@tool"]
  D --> S["ToolSpec<br/>name · description · JSON Schema"]
  S --> M["the model"]
  D --> T["Tool(spec, fn)"]
  T --> R["ToolRegistry"]
```

## 3. Tour of the given code

- **`harnessy/types.py`: `Tool` moved here** from `loop.py`, and gained two optional fields, `timeout_s` and `max_chars`, for per-tool limits. `from harnessy.loop import Tool` still works. (It moved because the registry needs `Tool` and the loop needs the registry. Leaving it in `loop.py` would be a circular import.)
- **`harnessy/tools/schema.py`**: `parse_docstring` splits a Google-style docstring into the description and per-parameter text. `tool` is the decorator. It works bare (`@tool`) or with options (`@tool(timeout_s=5, max_chars=2000)`), and returns a `Tool` whose `fn` is your original function.
- **`harnessy/tools/registry.py`**: `ToolRegistry.specs()` lists the specs in order. `ToolRegistry.expected(tool)` turns a tool's parameters into `"a: integer, b: integer"` for error messages.
- **`harnessy/tools/files.py`**: `file_tools(root)` returns `read_file` (line-numbered, with `offset` and `limit`) and `write_file`, both limited to one folder.
- **`harnessy/tools/web.py`**: `http_get`, built with `@tool` at import time.
- **`harnessy/tools/__init__.py` imports nothing, on purpose.** `web.py` runs `@tool` when it's imported, and `@tool` needs your exercises. If `__init__.py` imported it, every `harnessy.tools` import would fail until you'd finished the week. Import from the submodules instead: `from harnessy.tools.registry import ToolRegistry`.

## 4. The rules your validator follows

The model will send wrong arguments: a string where you wanted a number, a missing field, a field you never defined. Your registry checks the call against the schema **before** running the function, so the error names the exact problem.

It checks only what the schema says, using JSON Schema's own rules:

| Rule | Why it matters |
| --- | --- |
| Every name in `required` must be there | The most common mistake after a long conversation. |
| An unknown name is an error **only if `additionalProperties` is `false`** | JSON Schema allows extra names by default. `@tool` sets it to `false`. Your week 2 tests use hand-written specs that don't, so extra names still pass there, and a missing Python argument still ends up as a `TypeError`. That's why week 2 keeps passing. |
| Each value matches its `type` | `"17"` is not an `integer`. |
| **`True` is not an integer** | In Python, `isinstance(True, int)` is `True`. In JSON, a boolean is not a number. Check `bool` first. |
| An `int` *is* a valid `number` | `3` is fine where `3.0` is expected. |
| `enum` | For `Literal["asc", "desc"]` parameters. |
| Items of an `array` | One level deep is enough. |
| `null` for an optional parameter counts as "not given" | Models often send `"text": null` for a parameter they mean to skip. Accept it, then drop it before the call so the function's default applies. |
| `{"_raw": ...}` | Week 1's marker for arguments that weren't valid JSON. Say that, rather than "unknown parameter `_raw`". |

## 5. Errors are instructions

Every error your registry returns ends with what to do next:

```
Invalid arguments for 'add': 'a' must be integer, got str 'seventeen'. Expected parameters: a: integer, b: integer.
Unknown tool 'sub'. Available tools: add, read_file.
Tool 'http_get' timed out after 15s. Try a smaller request.
```

The model reads these on the next step. A good error message is the cheapest way to get a model to fix its own call. The `test_wiring.py` "done when" test checks exactly this: a bad call, a readable error, then a fixed call.

**Timeouts, with one caveat.** The registry runs each tool in a worker thread and waits at most `timeout_s`. When the wait runs out, the loop moves on, but Python can't kill a thread, so a hung tool keeps running in the background. Make it a **daemon** thread (`threading.Thread(..., daemon=True)`): a `ThreadPoolExecutor` worker would keep your whole program from exiting until the hung tool finished, possibly forever. `test_a_hung_tool_does_not_keep_the_process_alive` checks this. A thread that keeps running is fine for reads. It's not fine for a tool that changes things. Week 7 moves risky tools into a subprocess that can be killed.

Every path a call can take through `ToolRegistry.call`:

```mermaid
flowchart LR
  IN(["ToolCall"]) --> K{"known tool?"}
  K -- no --> E1["error: Unknown tool 'x'.<br/>Available tools: …"]
  K -- yes --> V{"validate_args<br/>against the schema"}
  V -- problems --> E2["error: Invalid arguments …<br/>Expected parameters: a: integer, …"]
  V -- ok --> N["drop null optional args<br/>so defaults apply"]
  N --> T["run fn in a daemon thread<br/>wait timeout_s"]
  T -- still running --> E3["error: timed out after Ns"]
  T -- TypeError --> E4["error: Bad arguments …"]
  T -- other exception --> E5["error: Tool 'x' failed: Type: msg"]
  T -- returned --> S["str() it, then truncate<br/>to max_chars with a note"]
  S --> OUT(["ToolResult"])
  E1 --> OUT
  E2 --> OUT
  E3 --> OUT
  E4 --> OUT
  E5 --> OUT
  classDef err fill:#fbf0e1,stroke:#a65b00,color:#1b2230
  class E1,E2,E3,E4,E5 err
```

*Fig 6 in [docs/architecture.md](../docs/architecture.md#fig-6-a-tool-call-through-the-registry).*

## 6. Truncation

One `read_file` on a log file can be 50,000 characters, and all of it would go into the context. So the registry cuts every result to `max_chars` (4,000 by default) and **says it did**:

```
[truncated: showing the first 4,000 of 51,200 characters]
```

If you cut silently, the model thinks it saw everything. With the note, it can ask for the next part. `read_file` goes one step further and tells the model exactly how: `call again with offset=201 for more`.

## 7. Safety lives in code

`file_tools(root)` can only touch files inside `root`. That's enforced by `resolve_inside`, not by a line in the system prompt. It has to reject three kinds of path:

- `../secret`: the `..` climbs out.
- `/etc/passwd`: in Python, `root / "/etc/passwd"` *is* `/etc/passwd`.
- `link/secret`, where `link` is a symlink pointing outside. `Path.resolve()` follows it, so check *after* resolving.

A rejected path raises `ValueError`, and the registry turns that into an error result like any other tool failure.

## 8. Exercises

Do them in this order. `@tool` needs 3a and 3b, and most other tests use `@tool`.

Until 3a and 3b pass, four test files (`test_registry.py`, `test_web.py`, both `test_wiring.py`) show up as **collection errors**: they use `@tool` at import time, and the error names the exercise to finish. Every other test still runs.

| # | Function | File | Tests |
| --- | --- | --- | --- |
| 3a | `json_type` | `tools/schema.py` | `uv run pytest tests/week3/test_schema.py -k "types or literal or optional or unsupported"` |
| 3b | `schema_from_function` | `tools/schema.py` | `uv run pytest tests/week3/test_schema.py` |
| 3c | `validate_args` | `tools/registry.py` | `uv run pytest tests/week3/test_registry.py -k "no_problems or missing_required or unknown_param or wrong_type or bool or valid_number or enum or array_items or json_marker"` |
| 3d | `truncate` | `tools/registry.py` | `uv run pytest tests/week3/test_registry.py -k test_truncate` |
| 3e | `ToolRegistry.call` | `tools/registry.py` | `uv run pytest tests/week3/test_registry.py` |
| 3f | `resolve_inside` | `tools/files.py` | `uv run pytest tests/week3/test_files.py tests/week3/test_web.py` |

Hints:

- **3a:** `typing.get_origin(list[int])` is `list` and `get_args` gives `(int,)`. `str | None` has origin `types.UnionType`, while `Optional[str]` has origin `typing.Union`. Handle both.
- **3b:** use `typing.get_type_hints(fn)`, not `param.annotation`, because it resolves string annotations like `"int"` from `from __future__ import annotations`.
- **3c:** write a small `_type_ok(value, schema)` helper, and check `bool` before the `isinstance` test.

## 9. Wire it into your loop

Your `Agent` still runs tools its own way, with the `_by_name` dict from week 2. Hand that job to the registry. In **your** `harnessy/loop.py`:

1. Add the import:

   ```python
   from harnessy.tools.registry import ToolRegistry
   ```

2. Replace the `_by_name` field and `__post_init__` with:

   ```python
       _registry: ToolRegistry = field(init=False, repr=False)

       def __post_init__(self) -> None:
           self._registry = ToolRegistry(self.tools)
   ```

3. In `run`, get the specs from the registry: `specs = self._registry.specs()`.
4. Replace the whole body of `_run_tool` with:

   ```python
           return self._registry.call(call)
   ```

Then run:

```bash
uv run pytest tests/week2 tests/week3
```

Week 2 must still pass. Its error-handling tests now go through the registry.

## 10. Try it live

```bash
uv run python -m scripts.week3_demo                     # both providers
uv run python -m scripts.week3_demo --provider openai
```

Each run gets a fresh temporary folder. You should see `write_file`, then `read_file` with line numbers, then an answer of 3 lines, and the script prints the file it found on disk.

**Stretch.** Give `write_file` two descriptions, a one-liner and a detailed one, and run the demo 5 times with each. Write down how often the model called it correctly the first time. In week 5 you'll turn this into a real eval.

## 11. Check yourself

- `HARNESSY_IMPL=solutions uv run pytest tests/week3` runs the tests against the reference solutions.
- `diff harnessy/tools/registry.py solutions/harnessy/tools/registry.py` once yours passes.
- `diff harnessy/loop.py solutions/harnessy/loop.py` shows your loop next to the reference, with the wiring in both.

## 12. Notes for `NOTES.md`

1. In the demo, did either model ever get a validation error? If you force one (rename a parameter in the prompt), what does the model do with the message on the next step?
2. Name one tool you'd want in a real agent that should be confined the way `file_tools` is. What is its "root"?
3. Longer descriptions cost tokens on every single call. When is that worth it?
