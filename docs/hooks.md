# Hooks: changing the loop without editing it

Week 6 adds hooks. This page explains where they fire, what each one can return, how several hooks combine, and the four hooks harnessy already has. It then gives six hooks you can write yourself, each checked against `ScriptedModel`, and ends with a map from these hooks to the ones in Claude Code, Codex and the OpenAI Agents SDK.

> **In one line:** a hook is code the agent loop calls at fixed points in a run, so you can **watch**, **change** or **block** what happens without touching `loop.py`.

## 1. A hook is a class with optional methods

Inherit from `Hook` (`solutions/harnessy/hooks.py`) and override only what you need. Every default method does nothing and returns `None`, and `None` always means "change nothing".

```python
from harnessy.hooks import Hook, Block

class MyHook(Hook):
    def before_tool(self, call):
        if call.name == "delete_everything":
            return Block("No.")
        return None          # every other call runs unchanged
```

Pass it to the agent: `Agent(model, tools=..., hooks=[MyHook()])`.

## 2. Where hooks fire

```mermaid
flowchart TD
  START(["run(task)"]) --> OS["<b>on_start</b>(agent, task)"]:::obs
  OS --> PREP["view = context.prepare(history)"]
  PREP --> BM["<b>before_model</b>(view)"]:::chg
  BM -->|"Block"| BLK(["run ends<br/>stop_reason: blocked"]):::stop
  BM --> CALL["model.complete(view)"]
  CALL --> AM["<b>after_model</b>(response)"]:::chg
  AM --> Q{"tool calls?"}
  Q -->|yes, for each| BT["<b>before_tool</b>(call)"]:::chg
  BT -->|"Block"| ERR["error result<br/>(the model reads the reason)"]
  BT --> RUN["registry.call(call)"]
  RUN --> AT["<b>after_tool</b>(call, result)"]:::chg
  ERR --> AT
  AT --> PREP
  Q -->|"no: end_turn"| ST["<b>on_stop</b>(result)"]:::chg
  ST -->|"a message: 'not yet'"| PREP
  ST -->|None| OF["<b>on_finish</b>(result)"]:::obs
  OF --> END(["RunResult"])
  classDef obs fill:#f6f7fb,stroke:#9aa3c0
  classDef chg fill:#e8f0fe,stroke:#4a6fd8
  classDef stop fill:#fdf0ee,stroke:#c9563c
```

The blue boxes can change what happens; the grey ones only watch. `on_finish` runs however the run ended: after a block, an error or a step limit, too.

| Hook point | Return | Effect |
| --- | --- | --- |
| `on_start(agent, task)` | – | Watch. Reset per-run state here. |
| `before_model(view)` | new view, `Block` or `None` | Change what the model sees. A `Block` **ends the run** (`stop_reason="blocked"`). |
| `after_model(response)` | new response or `None` | Change what the model said. |
| `before_tool(call)` | new call, `Block` or `None` | Change the arguments, or refuse. A `Block` becomes an **error result the model reads**, and the run continues. |
| `after_tool(call, result)` | new result or `None` | Change what the model gets back. |
| `on_stop(result)` | a message or `None` | Turn down "done": the message goes to the model as a user turn. |
| `on_finish(result)` | – | Watch the final result. |

### The two kinds of `Block`

```mermaid
flowchart LR
  subgraph BMB["Block in before_model"]
    direction TB
    A1["'don't call the model again'"] --> A2(["the run ends<br/>stop_reason: blocked"])
  end
  subgraph BTB["Block in before_tool"]
    direction TB
    B1["'don't run this tool'"] --> B2["ToolResult(is_error=True,<br/>content=reason)"] --> B3(["the model reads it<br/>and tries something else"])
  end
  style BMB fill:#fdf0ee,stroke:#c9563c
  style BTB fill:#fff6e0,stroke:#d19a1c
```

A refused tool call isn't a crash. Like any tool failure since week 3, it's a *result* the model can react to.

## 3. Several hooks: they chain

`HookRunner` runs the hooks in list order:

```mermaid
flowchart LR
  V0["view"] --> H1["hook 1<br/>returns None"] -->|"same view"| H2["hook 2<br/>returns a new view"] -->|"hook 2's view"| H3["hook 3<br/>returns None"] --> V3["view sent<br/>to the model"]
  H1 -.->|"if it returns Block"| X(["stop: later hooks<br/>don't run"])
```

- **One feeds the next.** Each hook gets what the previous one returned. `None` passes the current value along.
- **The first `Block` wins.** In `before_model` and `before_tool`, later hooks don't run.
- **`on_stop`:** the first hook that returns a message wins.
- **Blocked calls still reach `after_tool`,** as error results, so a tracer still records them.

**Order matters.** Put hooks that change things *before* hooks that record them:

```python
hooks=[RedactSecrets(), approvals, TraceHook(tracer)]
#      ^ cleans results  ^ refuses calls  ^ records what really happened, secrets already gone
```

## 4. The four hooks harnessy already has

```mermaid
flowchart LR
  subgraph POINTS["Hook points"]
    direction TB
    p1["on_start"]
    p2["before_model"]
    p3["after_model"]
    p4["before_tool"]
    p5["after_tool"]
    p6["on_stop"]
    p7["on_finish"]
  end
  TR["TraceHook<br/><i>tracer.py</i>"]:::obs
  AP["ApprovalHook<br/><i>approvals.py</i>"]:::guard
  TD["TodoList<br/><i>todo.py</i>"]:::view
  SC["StopCheck<br/><i>hooks.py</i>"]:::stop
  TR --- p1 & p3 & p5 & p7
  AP --- p4
  TD --- p1 & p2
  SC --- p1 & p6
  classDef obs fill:#f6f7fb,stroke:#9aa3c0
  classDef guard fill:#fdf0ee,stroke:#c9563c
  classDef view fill:#eef8ee,stroke:#3a9a4a
  classDef stop fill:#fff6e0,stroke:#d19a1c
```

| Hook | What it does | Read more |
| --- | --- | --- |
| **`TraceHook`** | Writes week 5's JSONL trace: `run_start`, `model_call`, `tool_result` and `stop`. It only watches. | [`traces.md`](traces.md) |
| **`ApprovalHook`** | A policy per tool: `allow`, `ask` or `deny`. With `ask`, an approver function decides (for example, y/N in the terminal). | week 6, section 5 |
| **`TodoList`** | Adds the current plan to the end of the view on every call, never to the history. | [`todo.md`](todo.md) |
| **`StopCheck`** | Turns down "done" while `check(result)` returns a message, at most `max_rejections` times (2 by default). | week 6, section 8 |

All four together:

```python
todo = TodoList()
agent = Agent(model,
    tools=[*file_tools(root), todo.tool()],
    hooks=[
        ApprovalHook({"write_file": "ask"}, approver=terminal_approver),  # y/N before each write
        todo,                                                             # the plan in every view
        StopCheck(lambda r: None if (root / "report.md").exists()
                  else "report.md doesn't exist yet."),                   # no "done" without it
        TraceHook(Tracer("run.jsonl")),                                   # record everything
    ])
```

### Why hooks exist

```mermaid
flowchart LR
  subgraph W5["Week 5: features inside the loop"]
    direction TB
    L5["loop.py<br/>if self.tracer: …<br/>if self.tracer: …<br/>if self.tracer: …<br/>if self.tracer: …"]
  end
  subgraph W6["Week 6: features as hooks"]
    direction TB
    L6["loop.py<br/>self._hooks.before_model(…)<br/>self._hooks.after_tool(…)"]
    L6 --- T6["TraceHook"]
    L6 --- A6["ApprovalHook"]
    L6 --- D6["TodoList"]
    L6 --- S6["StopCheck"]
    L6 --- Y6["yours"]
  end
  W5 -->|"week 6"| W6
```

In week 5 you wrote tracing as four `if self.tracer:` blocks inside the loop. Every new feature would have meant more of them. With hooks, the loop calls seven fixed points, and features plug in from outside.

## 5. Six hooks you can write

Each of these was run against `ScriptedModel` with the solution code, and the output under each example is what came back.

```python
import re, time
from dataclasses import replace
from harnessy.hooks import Hook, Block
```

### Example 1: Hide secrets in tool output

`after_tool` changes a result.

```mermaid
flowchart LR
  T["read_file app.log"] --> R["'connected with key sk-abc…123'"] --> H["RedactSecrets<br/>after_tool"]:::chg --> M["the model sees<br/>'connected with key [REDACTED]'"]
  classDef chg fill:#e8f0fe,stroke:#4a6fd8
```

```python
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})")

class RedactSecrets(Hook):
    def after_tool(self, call, result):
        clean = SECRET.sub("[REDACTED]", result.content)
        return replace(result, content=clean) if clean != result.content else None
```

```
model saw:     1	connected with key [REDACTED]
```

The key never reaches the model. It never reaches the trace either, as long as `TraceHook` comes after this hook.

### Example 2: Keep writes inside `drafts/`

`before_tool` changes or refuses a call.

```mermaid
flowchart LR
  C1["write_file('notes.md')"] --> H{"DraftsOnly<br/>before_tool"}:::chg
  C2["write_file('../etc/x')"] --> H
  H -->|"rewrite"| OK["write_file('drafts/notes.md')"]
  H -->|"Block"| NO["error result:<br/>'Refused: outside the workspace'"]
  classDef chg fill:#e8f0fe,stroke:#4a6fd8
```

```python
class DraftsOnly(Hook):
    def before_tool(self, call):
        if call.name != "write_file":
            return None
        path = call.arguments.get("path", "")
        if path.startswith("/") or ".." in path:
            return Block(f"Refused: {path!r} is outside the workspace. Use a path under drafts/.")
        if not path.startswith("drafts/"):
            return replace(call, arguments={**call.arguments, "path": f"drafts/{path}"})
        return None
```

```
is_error=False  Wrote 1 characters to drafts/notes.md
is_error=True   Refused: '../etc/x' is outside the workspace. Use a path under drafts/.
```

Quietly rewriting `notes.md` to `drafts/notes.md` is a design choice. You could block it with a message instead, so the model knows where its file went.

### Example 3: A token budget

`after_model` counts and `before_model` stops.

```mermaid
sequenceDiagram
  participant L as Loop
  participant H as TokenBudget
  participant M as Model
  L->>H: before_model (used 0)
  H-->>L: None
  L->>M: complete
  M-->>L: 900 in + 200 out
  L->>H: after_model → used = 1,100
  Note over L: runs the tool
  L->>H: before_model (used 1,100 ≥ 1,000)
  H-->>L: Block("token budget of 1000 used up")
  Note over L: the run ends, stop_reason: blocked
```

```python
class TokenBudget(Hook):
    def __init__(self, max_tokens):
        self.max_tokens, self.used = max_tokens, 0
    def on_start(self, agent, task):
        self.used = 0
    def after_model(self, response):
        self.used += response.usage.input_tokens + response.usage.output_tokens
    def before_model(self, view):
        if self.used >= self.max_tokens:
            return Block(f"token budget of {self.max_tokens} used up")
```

```
stop_reason=blocked  error='token budget of 1000 used up'  model calls: 1
```

**Reset in `on_start`.** A hook object can be reused across runs, so per-run counters belong in `on_start`. The loop already has `max_tokens_total`, and week 7 adds `max_cost_usd`. This hook shows how such a limit can be built from outside the loop.

### Example 4: Find slow tools

This one only watches.

```python
class ToolTimer(Hook):
    def before_tool(self, call):
        self._t = time.monotonic()
    def after_tool(self, call, result):
        print(f"{call.name}: {time.monotonic() - self._t:.2f}s")
```

```
read_file: 0.00s
```

It returns `None` at both points, so the run is exactly the same with or without it.

### Example 5: "Run the tests before you say done"

`on_stop` turns down "done".

```mermaid
sequenceDiagram
  participant M as Model
  participant L as Loop
  participant H as TestsMustPass
  M-->>L: end_turn "done"
  L->>H: on_stop
  H->>H: run_tests() → FAILED test_mean
  H-->>L: "The tests still fail: … Fix them before finishing."
  L->>M: that text as a user turn
  M-->>L: end_turn "fixed, done"
  L->>H: on_stop
  H->>H: run_tests() → ok
  H-->>L: None
  Note over L: the run ends, end_turn
```

```python
class TestsMustPass(Hook):
    def __init__(self, run_tests):
        self.run_tests = run_tests          # () -> (ok: bool, output: str)
    def on_stop(self, result):
        ok, output = self.run_tests()
        return None if ok else f"The tests still fail:\n{output[-1500:]}\nFix them before finishing."
```

```
stop_reason=end_turn  final_text='fixed, done'  rejection sent: 'The tests still fail:\nFAILED test_mean…'
```

**This one can argue forever.** `StopCheck` caps rejections at 2, but this hand-written version has no cap. Only the loop's own limits (`max_steps`, `timeout`, and the token and cost caps) stop a model that can't make the tests pass. Add a counter, or use `StopCheck(check)` instead.

### Example 6: Add a reminder to every call

`before_model` changes the view, not the history.

```mermaid
flowchart LR
  H[("history<br/>'hi'")] --> R["Reminder<br/>before_model"]:::chg --> V["view<br/>'hi<br/><br/>Answer in British English.'"] --> M["Model"]
  H -.->|"unchanged"| RR["RunResult.messages<br/>'hi'"]
  classDef chg fill:#e8f0fe,stroke:#4a6fd8
```

```python
class Reminder(Hook):
    def __init__(self, text):
        self.text = text
    def before_model(self, view):
        last = view[-1]
        return [*view[:-1], replace(last, text=f"{last.text}\n\n{self.text}".strip())]
```

```
view: 'hi\n\nAnswer in British English.'   history: 'hi'
```

This is the same trick `TodoList` uses. Use `dataclasses.replace` and return a *new* list; never edit the messages you were given.

## 6. Testing a hook without spending tokens

`ScriptedModel` replays responses you prepare, so you can check a hook in milliseconds:

```python
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.types import ToolCall

model = ScriptedModel([
    tool_reply(ToolCall("c1", "read_file", {"path": "app.log"})),   # step 0: the model asks for a tool
    text_reply("ok"),                                                # step 1: the model is done
])
Agent(model, tools=file_tools(root), hooks=[RedactSecrets()]).run("read the log")

# model.calls[i] is exactly what the model was sent on call i
result_seen = model.calls[1].messages[-1].tool_results[0].content
assert "[REDACTED]" in result_seen
```

Week 6's tests (`tests/week6/test_hooks.py` and `test_wiring.py`) use this same pattern.

## 7. Hook or tool?

```mermaid
flowchart TD
  Q{"Who decides that<br/>it happens?"} -->|"the model, when it wants to"| TOOL["<b>Tool</b><br/>read a file · plan · delegate"]
  Q -->|"you, every time,<br/>whatever the model wants"| HOOK["<b>Hook</b><br/>approvals · limits · redaction<br/>tracing · stop checks"]
  Q -->|"both"| BOTH["<b>Tool + hook</b><br/>TodoList: the model writes the plan,<br/>the hook makes sure it sees it"]
  style TOOL fill:#e8f0fe,stroke:#4a6fd8
  style HOOK fill:#eef8ee,stroke:#3a9a4a
  style BOTH fill:#fff6e0,stroke:#d19a1c
```

## 8. From harnessy to the harnesses you use

Hooks are not a harnessy idea. Claude Code, OpenAI's Codex and the OpenAI Agents SDK all have them, at nearly the same points. Once you know the seven points on this page, you already know where to look in each of them. Two pages go into detail: [`claude-code-hooks.md`](claude-code-hooks.md) and [`openai-hooks.md`](openai-hooks.md).

### Two shapes of hook

```mermaid
flowchart TD
  Q{"Who owns the loop?"}
  Q -->|"your Python code calls it"| LIB["<b>A library</b><br/>harnessy · OpenAI Agents SDK"]
  Q -->|"a product you configure"| PROD["<b>A product</b><br/>Claude Code · Codex"]
  LIB --> L1["a hook is a <b>class</b><br/>registered in code<br/>gets and returns Python objects"]:::lib
  PROD --> P1["a hook is a <b>program</b><br/>registered in a settings file<br/>JSON on stdin, exit code + JSON on stdout"]:::prod
  classDef lib fill:#e8f0fe,stroke:#4a6fd8
  classDef prod fill:#eef8ee,stroke:#3a9a4a
```

The idea is the same in both shapes: fixed points, and at each one a hook can watch, change or block. The second shape exists because a product can't import your Python class. Your hook might be a shell script, so everything crosses a process boundary as text.

### The seven points, in four harnesses

```mermaid
flowchart LR
  subgraph HY["harnessy"]
    direction TB
    a1["on_start"]
    a2["before_model"]
    a3["after_model"]
    a4["before_tool"]
    a5["after_tool"]
    a6["on_stop"]
    a7["on_finish"]
  end
  subgraph CC["Claude Code and Codex"]
    direction TB
    b1["SessionStart"]
    b2["UserPromptSubmit<br/><i>once per prompt</i>"]
    b4["PreToolUse<br/>PermissionRequest"]
    b5["PostToolUse"]
    b6["Stop"]
    b7["SessionEnd"]
  end
  subgraph SDK["OpenAI Agents SDK"]
    direction TB
    c1["on_agent_start"]
    c2["on_llm_start<br/>input guardrail"]
    c3["on_llm_end"]
    c4["on_tool_start<br/>tool input guardrail"]
    c5["on_tool_end<br/>tool output guardrail"]
    c7["on_agent_end<br/>output guardrail"]
  end
  a1 --- b1
  a2 -.- b2
  a4 --- b4
  a5 --- b5
  a6 --- b6
  a7 --- b7
  b1 ~~~ c1
  b2 ~~~ c2
  b4 ~~~ c4
  b5 ~~~ c5
  b7 ~~~ c7
  style HY fill:#f6f7fb,stroke:#9aa3c0
  style CC fill:#eef8ee,stroke:#3a9a4a
  style SDK fill:#e8f0fe,stroke:#4a6fd8
```

Read each row across. A solid line is a direct match and the dotted one is a partial match; a gap in a column means that harness has no hook at that point.

| harnessy | Claude Code | Codex | OpenAI Agents SDK |
| --- | --- | --- | --- |
| `on_start` | `SessionStart` | `SessionStart` | `on_agent_start` |
| `before_model` → new view | `UserPromptSubmit` adds context, **once per prompt** | the same | – (`on_llm_start` only watches) |
| `before_model` → `Block` | `"continue": false` | `"continue": false` | input guardrail tripwire |
| `after_model` | – | – | `on_llm_end` (watch) |
| `before_tool` → `Block` | `PreToolUse`: `permissionDecision: "deny"` | the same | tool input guardrail: `reject_content` |
| `before_tool` → new call | `PreToolUse`: `updatedInput` | `updatedInput`, with `allow` | – |
| `after_tool` → new result | `PostToolUse`: `updatedToolOutput` | swap for feedback text only | tool output guardrail: swap for a message |
| `on_stop` → "not yet" | `Stop`: `decision: "block"` + `reason` | the same | – |
| `on_finish` | `SessionEnd` | `SessionEnd` | `on_agent_end` |
| `ApprovalHook` | `permissions` rules + `PermissionRequest` | approval policy + `PermissionRequest` | `needs_approval=True` on a tool |
| `StopCheck(max_rejections=2)` | `stop_hook_active`, and a cap of 8 | `stop_hook_active` | – |

### Three things that change when you leave harnessy

```mermaid
flowchart LR
  subgraph ONE["1. A chain becomes a vote"]
    direction TB
    o1["harnessy: hooks run in order,<br/>each gets the last one's result"] --> o2["Claude Code, Codex: hooks run<br/>in parallel; the strictest answer wins"]
  end
  subgraph TWO["2. before_model disappears"]
    direction TB
    t1["harnessy: a hook before<br/>every model call"] --> t2["Claude Code, Codex: one event<br/>per prompt you type"]
  end
  subgraph THREE["3. 'Change' and 'block' may split"]
    direction TB
    h1["harnessy: one Hook class<br/>watches, changes and blocks"] --> h2["Agents SDK: hooks watch,<br/>guardrails block"]
  end
  style ONE fill:#fff6e0,stroke:#d19a1c
  style TWO fill:#fdf0ee,stroke:#c9563c
  style THREE fill:#e8f0fe,stroke:#4a6fd8
```

1. **Order stops mattering.** Section 3's rule, "put hooks that change things before hooks that record them", has no equivalent in Claude Code or Codex. Hooks there can't see each other's changes, so keep all the rewriting for one tool in one hook.
2. **No hook before every model call.** `TodoList`, `Reminder` and `TokenBudget` all rely on `before_model`. None of them ports directly: a reminder moves to `CLAUDE.md` or `AGENTS.md`, and a budget moves to the product's own limit.
3. **Blocking may be a different mechanism.** In the Agents SDK every lifecycle hook returns `None`. To refuse a tool call there you write a guardrail on the tool.

### How the six examples port

| Example | Claude Code | Codex | Agents SDK |
| --- | --- | --- | --- |
| 1. `RedactSecrets` | Yes: `updatedToolOutput` | Partly: withhold the output, can't mask it | Partly: withhold, can't mask |
| 2. `DraftsOnly` | Yes: `updatedInput` or `deny` | Deny: yes. Rewrite: the input is a patch, not a path | Refuse: yes. Rewrite: no |
| 3. `TokenBudget` | No: use `--max-budget-usd` | No | Yes: count in `on_llm_end`, raise in `on_llm_start` |
| 4. `ToolTimer` | Yes: `duration_ms` is given | Yes: time it yourself | Yes: `on_tool_start` + `on_tool_end` |
| 5. `TestsMustPass` | Yes: `Stop` | Yes: the same script | No: nothing turns down "done" |
| 6. `Reminder` | Once per prompt | Once per prompt | No: put it in `instructions` |

The working code for each cell is in the two companion pages, where every script and sample was run.

**Where to go next:** if you use Claude Code, read [`claude-code-hooks.md`](claude-code-hooks.md) and port one of your own hooks. If you use OpenAI, [`openai-hooks.md`](openai-hooks.md) covers Codex (Part A) and the Agents SDK (Part B), and ends with all four harnesses in one table.

## See also

- [`docs/claude-code-hooks.md`](claude-code-hooks.md): these hooks in Claude Code, with the six examples ported
- [`docs/openai-hooks.md`](openai-hooks.md): the same for Codex and the OpenAI Agents SDK
- `lessons/week6-control-flow.md`, sections 3 to 8, and exercises 6a and 6b
- `solutions/harnessy/hooks.py`, `approvals.py`, `todo.py`, and `TraceHook` in `tracer.py`
- [`docs/todo.md`](todo.md), [`docs/subagents.md`](subagents.md) (pass your hooks down to helpers), [`docs/traces.md`](traces.md)
