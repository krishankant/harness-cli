# Week 2: The agent loop

**Time:** about 5 hours (1.5 reading, 3 building, 30 minutes on notes).

**You're done when:**

1. `uv run pytest tests/week2` passes (18 tests), and
2. `uv run python -m scripts.week2_demo` answers "What is 17 + 25, and what time is it?" in 2–3 steps on both providers.

## 1. Read first

| Read | Look for |
| --- | --- |
| [How to Build an Agent](https://ampcode.com/notes/how-to-build-an-agent) (Thorsten Ball) | How little code a working agent needs. Notice where he handles tool errors. |
| [ReAct](https://arxiv.org/abs/2210.03629) (Yao et al., 2022): introduction and figures 1–2 | The think, act, observe cycle your loop implements. |
| The agent class in [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent/) | About 100 lines that score over 70% on SWE-bench Verified. List what it *doesn't* have. |

## 2. Anatomy of one run

An agent is a model called in a loop. Each time around, the model either answers or asks for tools; if it asks, you run them and hand back the results. Here's the demo question, turn by turn. Watch the message list grow.

**Step 0.** The loop starts with one message and calls the model.

```
messages = [ user: "What is 17 + 25, and what time is it?" ]
model → assistant: tool_calls = [add(a=17, b=25), get_time()]   stop_reason = tool_use
```

The loop appends the assistant turn, runs **both** tools in order, and appends **one** user turn holding **both** results:

```
messages = [ user: "What is 17 + 25 ...",
             assistant: [add(...), get_time()],
             user: tool_results = [42, "10:56"] ]
```

**Step 1.** The loop calls the model again with the whole history.

```
model → assistant: "17 + 25 = 42, and it's 10:56."   stop_reason = end_turn
```

No tool calls, so the loop stops and returns `RunResult(final_text=..., stop_reason="end_turn", steps=[...], usage=...)`.

Two details matter:

- **All results go back in one turn.** Split them across turns and some models learn to stop making parallel calls.
- **Every step is recorded** (`Step`) with its response and tool results. In week 5 this becomes your trace.

The same run as a sequence diagram:

```mermaid
sequenceDiagram
  autonumber
  participant U as Caller
  participant A as Agent.run
  participant M as Model
  participant T as Tools
  U->>A: run("What is 17 + 25, and what time is it?")
  loop every step
    A->>A: check limits: steps, tokens, time
    A->>M: complete(messages, specs, system)
    M-->>A: ModelResponse
    alt tool calls and a clean stop
      A->>T: add(17, 25)
      T-->>A: "42"
      A->>T: get_time()
      T-->>A: "10:56"
      Note over A: append ONE user turn holding both results
    else the model answers
      A-->>U: RunResult(final_text, "end_turn", steps, usage)
    end
  end
```

*The full version, with what later weeks add, is Fig 4 in [docs/architecture.md](../docs/architecture.md#fig-4-one-agent-run).*

## 3. Why the loop never raises

A loop that raises an exception throws away everything the run did so far. harnessy's loop turns every failure into data instead:

| What went wrong | What the loop does |
| --- | --- |
| The model asked for a tool that doesn't exist | Returns a `ToolResult(is_error=True)` naming the tools that do exist. The model usually corrects itself on the next step. |
| The model sent wrong arguments (`TypeError`) | Error result: "Bad arguments for 'add': ...". |
| The tool itself crashed | Error result with the exception type and message. |
| The tool returned a number, not text | `str()` it. Tools shouldn't have to care. |
| The model API call raised | Stop with `stop_reason="model_error"` and the error text in `RunResult.error`. |
| A limit was hit | Stop with that limit as the `stop_reason`. |

The caller always gets a `RunResult`, and the `stop_reason` says honestly how the run ended.

## 4. The limits

Every loop needs a limit, or one confused model can run forever and spend real money. You add three limits this week and a fourth in week 7:

| Limit | `stop_reason` | Guards against |
| --- | --- | --- |
| `max_steps` | `max_steps` | A model that keeps calling tools and never answers |
| `max_tokens_total` | `max_tokens` | Long runs that grow the context (and the bill) without bound |
| `timeout_s` | `timeout` | Slow tools or slow APIs |
| `max_cost_usd` (week 7) | | Money, directly |

**Check every limit *before* each model call**, not after. The model call is where the time and money go, so that's the moment to decide whether you can afford another one.

Every way a week 2 run can end:

```mermaid
stateDiagram-v2
  direction LR
  [*] --> Limits
  Limits --> max_steps : steps used up
  Limits --> max_tokens : token budget spent
  Limits --> timeout : clock ran out
  Limits --> Model : all clear
  Model --> model_error : exception, error, or max_tokens
  Model --> refused : refusal
  Model --> Tools : tool calls, clean stop
  Tools --> Limits
  Model --> end_turn : answer
  max_steps --> [*]
  max_tokens --> [*]
  timeout --> [*]
  model_error --> [*]
  refused --> [*]
  end_turn --> [*]
```

*The full version, with what later weeks add, is Fig 5 in [docs/architecture.md](../docs/architecture.md#fig-5-how-a-run-ends).*

## 5. Truncated tool calls

If the model runs out of output tokens halfway through writing a tool call, the reply may still contain that tool call, with arguments cut off mid-way, and `stop_reason` is `max_tokens`. Running it would call a tool with half an instruction. The same goes for a reply that stopped with `error` (for example, the context window filled up mid-reply) or was `refused`. So the rule is: **run tools only from a reply that finished cleanly. If `stop_reason` is `max_tokens`, `error` or `refused`, don't run the tools; stop with `model_error` (or `refused`).** There are tests for exactly this.

Don't narrow the rule to "only when `stop_reason` is `tool_use`". Some OpenAI-compatible servers return `stop` together with tool calls, and those calls are complete.

## 6. Testing without tokens or waiting

Two given tools make the loop testable offline:

- **`ScriptedModel`** (`harnessy/models/scripted.py`) replays a list of responses you prepare with `text_reply(...)` and `tool_reply(...)`, and records every call it receives in `.calls`. The tests use it to check exactly what the loop sent to the model. Queue an exception in the list to simulate an API failure.
- **An injectable clock.** `Agent(clock=...)` defaults to `time.monotonic`. The tests pass a fake clock that jumps 4 seconds per call, so a 10-second timeout test runs instantly.

Both patterns keep paying off. In week 5 you'll replay a real failed trace through `ScriptedModel` to reproduce a bug step by step.

## 7. Exercises

Both are in `harnessy/loop.py`. Do them in this order.

**2a. `Agent._run_tool(call)`.** Run one tool call and always return a `ToolResult`. Start here, because `run` depends on it.

```bash
uv run pytest tests/week2/test_loop.py -k "unknown or bad_arguments or tool_exception or non_string"
```

These tests go through `run`, so they'll pass only once `run` works too. Write `_run_tool` first anyway, then move on.

**2b. `Agent.run(task)`.** The docstring gives the six steps in order. Work up through the tests:

```bash
uv run pytest tests/week2/test_loop.py -k "plain_answer"          # the simplest loop
uv run pytest tests/week2/test_loop.py -k "tool_calls_run or usage" # tools and token counts
uv run pytest tests/week2/test_loop.py -k "max_steps or token_budget or timeout"
uv run pytest tests/week2/test_loop.py -k "model_exception or refusal or truncated or verbose or error_stop or errored"
uv run pytest tests/week2                                           # everything
```

## 8. Try it live

With `.env` filled in from week 1:

```bash
uv run python -m scripts.week2_demo                       # both providers
uv run python -m scripts.week2_demo --provider anthropic  # one provider
```

With `verbose=True`, every step prints a line like:

```
[step 0] stop=tool_use tokens=300/60 calls=add({'a': 17, 'b': 25}), get_time({}) text=''
    -> toolu_1: 42
    -> toolu_2: 10:56
[step 1] stop=end_turn tokens=400/20 calls=- text='17 + 25 = 42, and it is 10:56.'
stop=end_turn steps=2 tokens=780
```

Read it the way you'll read traces from now on. How many steps did it take? Did the model call both tools in one step, or one per step? Where did most of the tokens go?

Then try `--max-steps 1`. The run stops with `max_steps` after the first tool call, and you get a result instead of a crash.

## 9. Check yourself

- `HARNESSY_IMPL=solutions uv run pytest tests/week2` runs the tests against the reference loop.
- `HARNESSY_IMPL=solutions uv run python -m scripts.week2_demo` shows what a finished week looks like live.
- `diff harnessy/loop.py solutions/harnessy/loop.py` once yours passes.

## 10. Notes for `NOTES.md`

1. Your loop checks limits before each model call. What would go wrong if it checked only after?
2. Look at the token counts per step in the live trace. Why does the input count grow every step even though you only asked one question? (Hold on to this for week 4.)
3. The loop treats "unknown tool" as a result the model can fix. Name a failure where stopping the run would be better than letting the model retry.
