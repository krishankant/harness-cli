# Week 6: Control flow: hooks, approvals, subagents, planning

**Time:** about 5 hours (1.5 reading, 3 building, 30 minutes on notes).

**Before you start:** weeks 2–5 must pass, including the week 5 tracer wiring (`uv run pytest tests/week2 tests/week3 tests/week4 tests/week5`). This week you rework that wiring.

**You're done when:**

1. `uv run pytest tests/week6` passes (34 tests), and weeks 1–5 still pass after the wiring (section 10), and
2. `uv run python -m scripts.week6_demo` stops to ask before writing a file, and in part 2 the parent's history holds only the two helpers' answers.

## 1. Read first

| Read | Look for |
| --- | --- |
| [12-Factor Agents](https://github.com/humanlayer/12-factor-agents) (HumanLayer) | Owning your control flow, contacting humans through tool calls, and small focused agents. |
| [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (Anthropic) | An orchestrator with workers, and why subagents help: each gets its own clean context. Note the cost: about 15× the tokens of a normal chat. |
| [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (Anthropic) | Progress files and a setup agent that let work continue across context windows. |

## 2. Owning the control flow

Most production agents are not fully autonomous. They're mostly fixed code, with a few points where the model decides: which tool to call, and when it's done. Everything else is yours to control. That means asking a person before a risky action, refusing a tool, checking the work before accepting "done", and splitting a job across helpers.

You could add each of those as another `if` in `run`. After week 5 you've felt what that does: four `if self.tracer:` blocks scattered through the loop. This week you add **hook points** instead. The loop calls them at fixed moments, and everything else becomes a small class that plugs in.

## 3. The hook points

For diagrams of every hook point, how several hooks chain, and six example hooks (all tested): [`docs/hooks.md`](../docs/hooks.md).

```
on_start(agent, task)
loop:
    before_model(view)        -> new view | Block | None
    model.complete(...)
    after_model(response)     -> new response | None
    for each tool call:
        before_tool(call)     -> new call | Block | None
        run it (or not)
        after_tool(call, result) -> new result | None
    model says it's done:
        on_stop(result)       -> "not yet: …" | None
on_finish(result)             (every way a run ends; observe only)
```

| Hook | Returning a `Block` means | Returning something else means |
| --- | --- | --- |
| `before_model` | the run ends with stop reason `blocked` | send this view instead |
| `before_tool` | the model gets the reason as an **error result**, and the run continues | run this call instead |
| `after_model`, `after_tool` | (no Block) | use this response or result instead |
| `on_stop` | (no Block) | a string: send it to the model as a user message and keep going |

`None` always means "no change". `HookRunner` (your exercise) runs a list of hooks in order. Each one sees the previous one's output, and the first `Block` wins.

Exceptions in hooks are **not** caught: hooks are your code, and a bug in one should be loud. The one place they're caught is `before_model` and `after_model`, which sit inside the model call's `try`. A crash there ends the run as `model_error`, like any other failure of the model call.

The hook points in a full run, in the order the loop calls them:

```mermaid
sequenceDiagram
  autonumber
  participant U as Caller
  participant A as Agent.run
  participant H as HookRunner
  participant C as ContextManager
  participant M as Model
  participant R as ToolRegistry
  U->>A: run(task)
  A->>H: on_start(agent, task)
  loop every step
    A->>A: check limits: steps, tokens, time
    A->>C: prepare(history)
    C-->>A: view
    A->>H: before_model(view)
    H-->>A: view (or Block ends the run)
    A->>M: complete(view, specs, system)
    M-->>A: ModelResponse
    A->>H: after_model(response)
    alt tool calls and a clean stop
      loop each call, in order
        A->>H: before_tool(call)
        alt allowed
          A->>R: call(call)
          R-->>A: ToolResult
        else blocked
          H-->>A: Block(reason) becomes an error result
        end
        A->>H: after_tool(call, result)
      end
    else the model says it is done
      A->>H: on_stop(result)
      alt rejected
        H-->>A: "not yet" goes back as a user message
      else accepted
        A->>H: on_finish(result)
        A-->>U: RunResult
      end
    end
  end
```

*The full version, with what later weeks add, is Fig 4 in [docs/architecture.md](../docs/architecture.md#fig-4-one-agent-run).*

## 4. Tracing becomes a hook

`TraceHook(tracer)` (given, at the bottom of `tracer.py`) emits exactly the week 5 events from `on_start`, `after_model`, `after_tool` and `on_finish`. `Agent(tracer=…)` still works: `__post_init__` turns it into a `TraceHook` and adds it last, so it records what the other hooks decided. The `test_every_exit_path_writes_a_stop_event` test from week 5 keeps passing, now through the hook.

That's the pay-off: tracing, approvals, the todo list and stop checks are four features, and the loop only knows about hook points.

## 5. Approvals

```python
ApprovalHook({"write_file": "ask", "http_get": "deny"}, approver=terminal_approver, default="allow")
```

| Policy | What happens |
| --- | --- |
| `allow` | runs |
| `ask` | calls `approver(call)`; `True` runs it, `False` blocks it |
| `deny` | blocked |

A blocked call is **not** a crash. The model gets an error result, "The user declined 'write_file'. Ask what they want instead, or try another way.", and can adapt. That's the "contact humans through tool calls" idea from 12-Factor Agents: the approval is part of the conversation, not an exception.

`terminal_approver` asks y/N on the terminal. It's just a function from `ToolCall` to `bool`, so a web UI, a Slack button or an allow-list are all drop-in replacements.

How `ApprovalHook.before_tool` decides:

```mermaid
flowchart LR
  C(["ToolCall"]) --> P{"policy for this tool<br/>(else the default)"}
  P -- allow --> RUN(["None: the call runs"])
  P -- deny --> B1(["Block: not allowed by policy"])
  P -- ask --> Q{"approver set?"}
  Q -- no --> B2(["Block: needs approval"])
  Q -- yes --> Y{"approver(call)"}
  Y -- True --> RUN
  Y -- False --> B3(["Block: the user declined"])
  classDef bad fill:#fbf0e1,stroke:#a65b00,color:#1b2230
  class B1,B2,B3 bad
```

## 6. Subagents

`subagent_tool(model, tools)` gives the model a `spawn_subagent(task, tools)` tool. Each call runs a **new** `Agent`, with:

- a fresh context: only the `task` text, no parent history;
- only the tools the parent names;
- only the hooks you pass to `subagent_tool(..., hooks=[...])`, and no tracer.

**Pass your safety hooks down.** A helper with no hooks has no approval policy. If the parent's `write_file` is `deny` but a helper is given `write_file` and no `ApprovalHook`, the parent can get around its own policy just by delegating. Either give helpers only safe tools (the demo gives them `read_file` alone) or pass the same `ApprovalHook` in `hooks=`.

Only the child's final answer comes back. In the demo, the helpers read four files, but the parent's history never contains a file. It holds the task, one call to the helpers, their two summaries and the final answer.

The cost: every child is a whole agent run. The Anthropic post measured multi-agent research at about 15× the tokens of a chat. Use subagents when the parent's context is the bottleneck, not by default.

`@tool(timeout_s=600)`: the registry's default 30-second timeout would cut a child off mid-run, so the tool raises its own limit.

A delegation, step by step:

```mermaid
sequenceDiagram
  participant P as Parent Agent
  participant R as Registry
  participant S as spawn_subagent
  participant C as Child Agent
  participant M as Model
  P->>R: call spawn_subagent(task, tools=[read_file])
  R->>S: run (timeout 600 s)
  S->>C: new Agent(named tools, hooks passed down, max_steps 8)
  Note over C: fresh context: only the task text
  loop child steps
    C->>M: complete(child view)
    M-->>C: tool calls or answer
  end
  C-->>S: RunResult
  S-->>R: final text only
  R-->>P: ToolResult: the answer
  Note over P: file contents never reach the parent's history
```

*Fig 10 in [docs/architecture.md](../docs/architecture.md#fig-10-subagents).*

How the model decides to delegate, the levers you have over it, and six worked examples with diagrams: [`docs/subagents.md`](../docs/subagents.md).

## 7. The todo list

`TodoList` is two things at once:

- **A tool** (`todo(action, text, id)`) the model uses to plan: add, complete, list.
- **A hook** (`before_model`) that shows the current list to the model on every turn.

It adds the list to the **view**, the last message sent to the model, and never to the history. That's the week 4 split again: `RunResult.messages` stays an honest record, and the model still sees an up-to-date plan on every call. `test_the_todo_list_reaches_the_model_but_not_the_history` checks both halves through a real `Agent`.

Watch for one thing: the list lands at the *end* of the prompt, so it doesn't break the prompt cache's prefix.

What Claude actually does with the list (it ignores it unless told to plan), the levers that make it plan, and when the list is worth its cost: [`docs/todo.md`](../docs/todo.md).

## 8. Rejecting "done"

```python
StopCheck(lambda result: None if (workspace / "report.md").exists() else "report.md doesn't exist yet.")
```

When the model says it's done, `on_stop` can say "not yet". The message goes back as a user turn and the loop continues. `max_rejections` (default 2) stops a hook and a model arguing forever, and the loop's own limits still apply.

## 9. Exercises

| # | Function | File | Tests |
| --- | --- | --- | --- |
| 6a | `HookRunner.before_model`, `after_model`, `before_tool`, `after_tool`, `on_stop` | `hooks.py` | `uv run pytest tests/week6/test_hooks.py` |
| 6b | `ApprovalHook.before_tool` | `approvals.py` | `uv run pytest tests/week6/test_approvals.py` |
| 6c | `subagent_tool` | `subagents.py` | `uv run pytest tests/week6/test_subagents.py` |
| 6d | `TodoList.apply`, `render`, `before_model` | `todo.py` | `uv run pytest tests/week6/test_todo.py` |
| 6e | wire it in (section 10) | `loop.py` | `uv run pytest tests/week6/test_wiring.py` |

For 6c, the docstring gives the exact tool signature and docstring to use. The docstring matters, because `@tool` turns it into what the model reads.

## 10. Wire it into your loop

This is the biggest edit to your loop so far. In **your** `harnessy/loop.py`:

1. Imports:

   ```python
   from harnessy.hooks import Block, Hook, HookRunner
   from harnessy.tracer import TraceHook, Tracer
   ```

2. Add `"blocked"` to `RunStopReason`.
3. Fields: after `tracer`, add `hooks: list[Hook] | tuple[Hook, ...] = ()`, and after `_registry`, add `_hooks: HookRunner = field(init=False, repr=False)`.
4. In `__post_init__`:

   ```python
           self._hooks = HookRunner([*self.hooks, *([TraceHook(self.tracer)] if self.tracer else [])])
   ```

5. **Delete** all four `if self.tracer:` blocks from week 5.
6. `finish` calls `on_finish`, and the run starts with `on_start`:

   ```python
           def finish(reason: RunStopReason, text: str = "", error: str | None = None) -> RunResult:
               result = RunResult(text, reason, steps, usage, messages, error)
               self._hooks.on_finish(result)
               return result

           self._hooks.on_start(self, task)
   ```

7. The model call:

   ```python
               try:
                   view = self.context.prepare(messages) if self.context else messages
                   view = self._hooks.before_model(view)
                   if isinstance(view, Block):
                       return finish("blocked", error=view.reason)
                   response = self._hooks.after_model(self.model.complete(view, specs, self.system))
               except Exception as e:
                   return finish("model_error", error=f"{type(e).__name__}: {e}")
   ```

8. The last line of the loop, where the model is done:

   ```python
               rejection = self._hooks.on_stop(RunResult(text, "end_turn", steps, usage, messages))
               if rejection:
                   messages.append(Message(role="user", text=rejection))
                   continue
               return finish("end_turn", text)
   ```

9. `_run_tool`:

   ```python
       def _run_tool(self, call: ToolCall) -> ToolResult:
           checked = self._hooks.before_tool(call)
           if isinstance(checked, Block):
               return self._hooks.after_tool(call, ToolResult(call.id, checked.reason, is_error=True))
           return self._hooks.after_tool(checked, self._registry.call(checked))
   ```

   A blocked call still goes through `after_tool`, so the trace records it.

The whole reference `run` after this week, to compare with yours:

```python
    def run(self, task: str) -> RunResult:
        messages: list[Message] = [Message(role="user", text=task)]
        steps: list[Step] = []
        usage = Usage()
        specs = self._registry.specs()
        start = self.clock()

        def finish(reason: RunStopReason, text: str = "", error: str | None = None) -> RunResult:
            result = RunResult(text, reason, steps, usage, messages, error)
            self._hooks.on_finish(result)
            return result

        self._hooks.on_start(self, task)

        while True:
            if len(steps) >= self.max_steps:
                return finish("max_steps")
            if usage.total >= self.max_tokens_total:
                return finish("max_tokens")
            if self.clock() - start >= self.timeout_s:
                return finish("timeout")

            try:
                view = self.context.prepare(messages) if self.context else messages
                view = self._hooks.before_model(view)
                if isinstance(view, Block):
                    return finish("blocked", error=view.reason)
                response = self._hooks.after_model(self.model.complete(view, specs, self.system))
            except Exception as e:  # any model failure ends the run cleanly
                return finish("model_error", error=f"{type(e).__name__}: {e}")

            usage = usage + response.usage
            messages.append(response.message)

            if response.message.tool_calls and response.stop_reason not in ("max_tokens", "error", "refused"):
                results = tuple(self._run_tool(call) for call in response.message.tool_calls)
                messages.append(Message(role="user", tool_results=results))
                steps.append(Step(len(steps), response, results))
                self._log(steps[-1])
                continue

            steps.append(Step(len(steps), response))
            self._log(steps[-1])
            text = response.message.text
            if response.stop_reason == "refused":
                return finish("refused", text)
            if response.stop_reason in ("error", "max_tokens"):
                return finish("model_error", text, error=f"model stopped with '{response.stop_reason}'")
            rejection = self._hooks.on_stop(RunResult(text, "end_turn", steps, usage, messages))
            if rejection:
                messages.append(Message(role="user", text=rejection))
                continue
            return finish("end_turn", text)
```

Then run everything:

```bash
uv run pytest tests/week2 tests/week3 tests/week4 tests/week5 tests/week6
```

## 11. Try it live

```bash
uv run python -m scripts.week6_demo                 # asks you y/N before writing motto.txt
uv run python -m scripts.week6_demo --provider openai
uv run python -m scripts.week6_demo --yes           # approve automatically
```

Answer **n** the first time. Read what the model does with the refusal.

In part 2, compare the parent's token count with what the helpers must have spent reading the files. That gap is what a subagent buys.

**Stretch.** Build a `StopCheck` for a coding task. Give the agent the week 3 file tools and a small repo with a failing test. `check` runs `pytest` in the workspace and returns its output while the test still fails. The agent can't say "done" until the tests pass. (Run `pytest` with `subprocess.run(..., timeout=60)`; week 7 hardens this.)

## 12. Check yourself

- `HARNESSY_IMPL=solutions uv run pytest tests/week6`
- `HARNESSY_IMPL=solutions uv run python -m scripts.week6_demo --yes`
- `diff harnessy/loop.py solutions/harnessy/loop.py`

## 13. Notes for `NOTES.md`

1. What did the model do when you declined the write? Was that what you wanted, and what would you change in the refusal message?
2. In the subagent demo, `RunResult.usage` shows only the parent's tokens: each helper is a separate run whose usage never reaches it. Why is that a problem for a cost limit, and how would you pass the helpers' usage up? (Week 7 adds the cost meter.)
3. Name one rule from your own work that you'd enforce with a `before_tool` hook instead of a line in the system prompt.
