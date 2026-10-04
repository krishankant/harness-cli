# Week 4: Context and memory

**Time:** about 5 hours (1.5 reading, 3 building, 30 minutes on notes).

**Before you start:** weeks 2 and 3 must pass, including the week 3 wiring (`uv run pytest tests/week2 tests/week3`). The week 4 tests use `@tool` and run through your `Agent`.

**You're done when:**

1. `uv run pytest tests/week4` passes (34 tests) and weeks 1–3 still pass after the wiring (section 9), and
2. `uv run python -m scripts.week4_demo` finds the purple elephant with and without a `ContextManager`, and the second memory run recalls the colour from the first.

## 1. Read first

| Read | Look for |
| --- | --- |
| [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (Anthropic) | Context as a limited budget, loading data just in time, compaction, and note-taking. |
| [Context Engineering for AI Agents: Lessons from Building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | Keeping the prompt prefix stable so the cache keeps hitting, and using the file system as memory. |
| [Context Rot](https://www.trychroma.com/research/context-rot) (Chroma, 2025) | Measurements across 18 models showing quality drops as the input gets longer. |

## 2. Why context is a budget

Remember the week 2 note question: why does the input count grow every step? Because every call sends the **whole** history. Here's the week 4 demo on Claude, without any context management:

```
input tokens per step: [671, 3477, 6274, 9092, 11931]
```

Every file the agent reads stays in every later call. Thirty steps of that is slow and expensive, and the Context Rot reading shows it also makes the model worse. The context window is the agent's only working memory, and this week you decide what goes in it.

## 3. History and view

The most important rule from week 1 still holds: **the history is append-only.** `RunResult.messages` keeps every turn, unedited. Anthropic checks that its thinking blocks come back exactly as they were sent, and a debugger needs the full record.

So you don't shrink the history. You build a **view** from it on every call:

```
history (append-only, every turn)
   │
   ├─ clear_old_results   old, large tool results → one-line stubs
   │
   ├─ strategy.view(cut)  drop (or summarize) everything before the cut
   │
   ▼
view  ──►  model.complete(view, tools, system)
```

A view may **drop whole turns**, and it may **replace the content of old tool results**. It never edits an assistant turn, so `raw` replay keeps working.

What `ContextManager.prepare` does on every call:

```mermaid
flowchart TB
  H[("history<br/>append-only, every turn")] --> NEW{"same first message<br/>as last time?"}
  NEW -- no --> RESET["new run: forget the cut"]
  NEW -- yes --> CLR
  RESET --> CLR["clear_old_results<br/>results older than the last 3 and 500+ chars<br/>become stubs"]
  CLR --> STICKY["view at the current cut<br/>(prefix unchanged: cache keeps hitting)"]
  STICKY --> FIT{"estimate_tokens(view)<br/>over budget?"}
  FIT -- no --> OUT(["view sent to the model"])
  FIT -- yes --> CUT["find_cut<br/>earliest assistant turn that fits<br/>budget × 0.5 − reserve"]
  CUT --> STRAT{"strategy"}
  STRAT -- DropOldest --> D["task + everything after the cut"]
  STRAT -- Summarize --> SUM["model summarizes the dropped span<br/>read from the ORIGINAL history"]
  D --> OUT
  SUM --> OUT
```

*The full version, with what later weeks add, is Fig 7 in [docs/architecture.md](../docs/architecture.md#fig-7-building-the-view-from-the-history).*

## 4. Where to cut

Say the view keeps the task message and then everything from index `cut` on. Where can `cut` go?

Only **before an assistant turn**. Cut anywhere else and you get this:

```
user:      "Read the notes…"            ← the task, always kept
user:      tool_result for call c7      ← its tool_use was cut away
assistant: …
```

That's a tool result with no matching call, and Anthropic rejects the request. It also breaks the user/assistant alternation. If you cut right before an assistant turn, each tool call stays with its results and the roles still alternate. `find_cut` returns the **earliest** such cut that fits the target, so the view drops as little as possible.

A safe cut and an unsafe one, on the same history:

```mermaid
flowchart LR
  T["user: task"] --> A1["assistant: call c1"] --> U1["user: result c1"] --> A2["assistant: call c2"] --> U2["user: result c2"]
  OK(["cut here: before an assistant turn"]) -.-> A2
  BAD(["never here: result c2 would lose its call"]) -.-> U2
  classDef bad fill:#fbf0e1,stroke:#a65b00,color:#1b2230
  class BAD bad
```

## 5. Two strategies

| | `DropOldest` (given) | `Summarize` (exercise) |
| --- | --- | --- |
| What happens to the dropped turns | Gone | A model writes a summary, and it's added to the task message |
| Cost | Free | One extra model call per compaction |
| Risk | Forgets a fact found early | The summary can miss or garble details |

`Summarize` reads the **original** history, not the cleared view: `prepare` passes both, so a fact hidden behind a `[cleared: …]` stub still reaches the summary. And if the summary call is refused or cut off, `Summarize` raises instead of storing an empty summary; inside your loop's `try`, that ends the run as `model_error` rather than silently losing the dropped turns.

`Summarize` is incremental. The next compaction sends *the old summary plus only the newly dropped turns*, not the whole history again. It also remembers its last cut, so a view with the same cut costs no model call. Its model usage is kept on `Summarize.usage`, and it's **not** included in `RunResult.usage`. Week 7's cost meter fixes that.

Both strategies declare `reserve_tokens`: room the manager keeps free for what the strategy adds. That's 0 for `DropOldest` and 400 for the summary.

## 6. Keeping the cache warm

Providers cache the start of your prompt: the system prompt, the tool list and the oldest messages. If that prefix is byte-for-byte the same as last call, the cached part costs a fraction of the price and is faster. The Manus post is about exactly this.

So two rules:

- **System prompt and tools never change within a run.** `test_system_and_tools_are_identical_on_every_call` checks it.
- **The cut is sticky.** `ContextManager` moves the cut only when the view goes over `budget_tokens`, and then compacts well below it (`target_ratio=0.5`). Between compactions the start of the view stays identical, and only new turns are appended.

There's one honest trade-off. `clear_old_results` changes the view in the *middle* on most steps: the fourth-newest result becomes a stub. That costs some cache hits. It's the usual deal: less context in exchange for fewer cache hits.

## 7. Reading the demo

Here's the same task with `ContextManager(budget_tokens=3000)`:

```
without: steps=5  total=31,971  input per step: [671, 3477, 6274, 9092, 11931]
with:    steps=13 total=47,030  input per step: [671, 2176, 3968, 3647, 3603, 5099, 3489, 5255, …]
```

Three things to notice:

1. **The peak input is bounded.** It stays around 2,000–5,000 tokens instead of growing without limit. On a 30-step task, that's the difference between finishing and hitting the context window.
2. **The total went *up*.** Once a file's content was cleared, the model couldn't see it any more and went back to re-read files. Managing context is not free. When it removes something the model still needs, the model pays to get it back. That's why "which results are safe to clear?" is the real design question (see the notes).
3. **The budget isn't exact.** `estimate_tokens` counts only the messages, as characters divided by 4. The system prompt and tool specs are extra, and real tokenizers differ. Use the estimate for decisions, not accounting.

Your numbers will differ from run to run. Run it twice before you conclude anything. That's week 5's lesson.

## 8. Long-term memory

The context window resets every run. `MemoryStore` doesn't. It's a JSON file of `{key: text}`, and the agent reaches it through two tools, `remember(key, text)` and `recall(query)`.

That's the "file system as memory" idea from the Manus post. The agent decides what's worth keeping, and it pays for a memory only when it asks for one, instead of carrying every past fact in every prompt.

`recall` ranks by shared words, which is deliberately simple. The demo stored `favourite_colour: "The user's favourite colour is teal."` and the next run found it with "favourite colour". Swapping in embeddings is a good stretch once you have evals to tell whether it helped.

## 9. Exercises

| # | Function | File | Tests |
| --- | --- | --- | --- |
| 4a | `estimate_tokens` | `context.py` | `uv run pytest tests/week4/test_estimate.py` |
| 4b | `clear_old_results` | `context.py` | `uv run pytest tests/week4/test_clear.py` |
| 4c | `find_cut` | `context.py` | `uv run pytest tests/week4/test_cut.py` |
| 4d | `ContextManager.prepare` | `context.py` | `uv run pytest tests/week4/test_manager.py -k "not summarize"` |
| 4e | `Summarize.view` | `context.py` | `uv run pytest tests/week4/test_summarize.py tests/week4/test_manager.py` |
| 4f | `MemoryStore.recall` | `memory.py` | `uv run pytest tests/week4/test_memory.py` |

Hints:

- **4a:** when `raw` is set, count it *instead of* text and tool calls, because that's what the Anthropic adapter actually sends.
- **4b:** collect all `(message index, result index)` positions first, then decide which are old.
- **4e:** keep `self._cut` and `self._summary`, and use `dataclasses.replace` to build the new task message.

## 10. Wire it into your loop

In **your** `harnessy/loop.py`:

1. Add the import:

   ```python
   from harnessy.context import ContextManager
   ```

2. Add a field to `Agent`, after `printer`:

   ```python
       context: ContextManager | None = None
   ```

3. In `run`, replace the model call **inside the `try`** with:

   ```python
                   view = self.context.prepare(messages) if self.context else messages
                   response = self.model.complete(view, specs, self.system)
   ```

Keeping it inside the `try` means a failing summary call ends the run as `model_error`, the same as any other model failure. The history (`messages`) is still what you append to and return. Only the model sees the view.

Then run:

```bash
uv run pytest tests/week2 tests/week3 tests/week4
```

## 11. Try it live

```bash
uv run python -m scripts.week4_demo                          # Anthropic, budget 3,000
uv run python -m scripts.week4_demo --provider openai --budget 2000
```

**Stretch: prompt caching.** Add `cache_control` to the Anthropic adapter's request, and print `cache_read_input_tokens` from the usage for each step. Then watch what happens to it at each compaction.

## 12. Check yourself

- `HARNESSY_IMPL=solutions uv run pytest tests/week4`
- `HARNESSY_IMPL=solutions uv run python -m scripts.week4_demo`
- `diff harnessy/context.py solutions/harnessy/context.py`

## 13. Notes for `NOTES.md`

1. Copy both "input tokens per step" lines from your demo run. Where did the budget go before and after, and did the total go up or down? Why?
2. Describe a task where `DropOldest` loses something `Summarize` would keep, and one where the summary would be the thing that goes wrong.
3. Some tool results should never be cleared: a plan, the test output the agent is fixing, and so on. How would you mark them? (You'll get hooks for this in week 6.)
