# Week 5: Traces and evals

**Time:** about 5 hours (1.5 reading, 3 building, 30 minutes on notes).

**Before you start:** weeks 2–4 must pass, including their wiring (`uv run pytest tests/week2 tests/week3 tests/week4`). The eval runner drives your own `Agent`, with your tools and your context code.

**You're done when:**

1. `uv run pytest tests/week5` passes (45 tests), and weeks 1–4 still pass after the wiring (section 5), and
2. `uv run python -m scripts.evals --provider both --trials 3` prints a table for each provider, and changing one tool description visibly moves at least one number.

## 1. Read first

| Read | Look for |
| --- | --- |
| [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) (Anthropic, January 2026) | The vocabulary: a task vs a trial, a transcript vs an outcome. Grade the outcome first, and use model judges calibrated against people. |
| [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/) (Hamel Husain) | Look at your data first, analyse the errors, then write evals that target the failures you found. |

## 2. Why evals

Run the week 4 demo twice and you'll get two different step counts. Agents are random, so one good run proves little, and so does one bad run. Before this week, every change to a prompt or a tool was a guess.

The fix has two halves:

- **Traces.** Record what every run did, so you can see *why* it failed.
- **Evals.** Run a fixed set of tasks several times each, grade the **end result**, and count. The number you track is the pass rate over several trials, not "it worked when I tried it".

Two words from the reading, used throughout:

| | Means | In harnessy |
| --- | --- | --- |
| **Task** | One thing to do, with a way to check it | A YAML file in `evals/tasks/` |
| **Trial** | One attempt at a task | One `run_trial`, in its own fresh workspace |
| **Transcript** | Everything the agent did | The trace (`.jsonl`) |
| **Outcome** | What changed in the world | The files in the workspace, and the final answer |

## 3. The trace format

`Tracer(path)` appends one JSON line per event. Every line has `run_id`, `seq` (0, 1, 2, …), `t` (seconds since the run started) and `kind`, plus data for that kind:

| kind | data |
| --- | --- |
| `run_start` | `task`, `model`, `system`, `tools` (names) |
| `model_call` | `step`, `stop_reason`, `input_tokens`, `output_tokens`, `text`, `tool_calls` |
| `tool_result` | `step`, `name`, `arguments`, `tool_call_id`, `content`, `is_error` |
| `stop` | `stop_reason`, `steps`, `input_tokens`, `output_tokens`, `error`, `final_text` |

A `model_call` line looks like this:

```json
{"run_id": "3fa9c21e", "seq": 1, "t": 1.842, "kind": "model_call", "step": 0, "stop_reason": "tool_use", "input_tokens": 671, "output_tokens": 116, "text": "", "tool_calls": [{"id": "toolu_01…", "name": "write_file", "arguments": {"path": "hello.txt", "content": "Hello, harness!"}}]}
```

There are no timers in the loop. **How long something took is the gap between two events' `t`.** The time before a `model_call` is the model's; the time before a `tool_result` is the tool's.

JSON Lines is deliberately plain. You can `grep` it, `jq` it, load it into a notebook, or diff two runs, and a crash halfway through still leaves every line written so far.

When your loop writes each event:

```mermaid
sequenceDiagram
  participant A as Agent.run
  participant M as Model
  participant T as Tracer (JSONL)
  A->>T: run_start (task, model, system, tools)
  loop every step
    A->>M: complete(...)
    M-->>A: ModelResponse
    A->>T: model_call (step, stop_reason, tokens, text, tool_calls)
    opt tool calls
      A->>T: tool_result per call (step, name, arguments, content, is_error)
    end
  end
  A->>T: stop (stop_reason, steps, tokens, error, final_text) from finish()
```

## 4. Reading a timeline

`format_timeline` (your exercise) turns a trace back into something a person can read:

```
run 3fa9c21e  model=claude-opus-5  tools=read_file, write_file
task: Create a file named hello.txt containing exactly this text: Hello, harness!
[   1.84s + 1.84s] step 0 model tool_use in=671 out=116 write_file({"path": "hello.txt", "content": "Hello, harne...
[   1.85s + 0.01s]   write_file -> Wrote 15 characters to hello.txt
[   3.10s + 1.25s] step 1 model end_turn in=812 out=24 'Done: hello.txt now contains the text.'
[   3.10s] stop end_turn steps=2 tokens=1623
```

Print any saved trace with:

```bash
uv run python -m scripts.trace_view evals/results/traces/<run>/<task>-1.jsonl
```

For three real traces read line by line (no tools, one tool call, and a run where the model checks its own work), see [`docs/traces.md`](../docs/traces.md).

## 5. Wire it into your loop

In **your** `harnessy/loop.py`:

1. Add the import:

   ```python
   from harnessy.tracer import Tracer
   ```

2. Add a field after `context`:

   ```python
       tracer: Tracer | None = None
   ```

3. Put the `stop` event inside `finish`, so **every** way a run ends writes one. Emit `run_start` right after `start = self.clock()`:

   ```python
           def finish(reason: RunStopReason, text: str = "", error: str | None = None) -> RunResult:
               if self.tracer:
                   self.tracer.event(
                       "stop", stop_reason=reason, steps=len(steps), input_tokens=usage.input_tokens,
                       output_tokens=usage.output_tokens, error=error, final_text=text,
                   )
               return RunResult(text, reason, steps, usage, messages, error)

           if self.tracer:
               self.tracer.event("run_start", task=task, model=self.model.name, system=self.system, tools=[s.name for s in specs])
   ```

   `finish` has to come after `specs` and `start` are set.

4. Right after `messages.append(response.message)`:

   ```python
               if self.tracer:
                   self.tracer.event(
                       "model_call", step=len(steps), stop_reason=response.stop_reason,
                       input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
                       text=response.message.text, tool_calls=response.message.tool_calls,
                   )
   ```

5. Right after `results = tuple(...)`, before the results are appended:

   ```python
                   if self.tracer:
                       for call, res in zip(response.message.tool_calls, results):
                           self.tracer.event(
                               "tool_result", step=len(steps), name=call.name, arguments=call.arguments,
                               tool_call_id=res.tool_call_id, content=res.content, is_error=res.is_error,
                           )
   ```

Both new events use `step=len(steps)`, so they come before `steps.append(...)`. Run `uv run pytest tests/week2 tests/week3 tests/week4 tests/week5`. `test_every_exit_path_writes_a_stop_event` checks the limits, the model error and the refusal as well as the happy path.

In week 6 these four `if self.tracer:` blocks go away again: tracing becomes a hook. Writing them inline first is how you'll see why hooks are worth having.

## 6. Eval tasks

Each task is one YAML file:

```yaml
id: m03-fix-typo
difficulty: medium
toolsets: [files]          # files and/or memory; none at all for a pure question
max_steps: 6
prompt: "README.md misspells 'Installation' as 'Instalation'. Fix every occurrence and change nothing else."
files:                     # written into a fresh workspace for every trial
  README.md: |
    ...
checks:                    # all must pass
  - type: file_lacks
    path: README.md
    text: "Instalation"
  - type: file_contains
    path: README.md
    text: "See the Installation notes below for Windows."
```

There are 15 tasks: 5 easy, 5 medium and 5 hard. None of them need the network. `load_task` (your exercise) checks every file **when it is loaded**. A typo like `type: file_contain` otherwise wouldn't fail loudly. It would quietly score zero every time and look like a model problem.

## 7. Graders: outcome first

| Check | Passes when |
| --- | --- |
| `file_exists {path}` | the file is there |
| `file_contains {path, text}` | the file contains the text (case-sensitive) |
| `file_lacks {path, text}` | the file exists and does *not* contain the text |
| `answer_contains {text}` | the final answer contains the text (any case) |
| `answer_matches {pattern}` | a regex search on the answer (any case) |
| `json_valid {path, equals?}` | the file parses as JSON, and equals the value if one is given |
| `rubric {criteria, path?}` | a judge model says PASS (on the file if `path` is given, else on the answer) |

Rules the graders keep:

- **Check the world, not the transcript.** Did `people.json` come out right? It doesn't matter whether the agent used one step or four.
- **Code first, judge last.** Only `m05-haiku-rubric` needs a model to decide ("is this a haiku about bees?"), and even that task also checks that the file exists. A judge is another random model. Calibrate it against your own judgement before you trust it (see the reading).
- **Graders never raise.** A bad check, a missing file or a path outside the workspace gives a failed `CheckResult` with a readable detail.

`judge_verdict` parses the judge's reply by its first word. Models add decoration, so `**PASS** - three lines about bees.` must count as PASS. Anything that isn't clearly PASS or FAIL is a failed check with "judge reply unclear".

## 8. The runner and saved results

`run_trial` (given) does one trial:

1. Makes a fresh temp workspace and writes the task's files into it.
2. Builds the tools from `toolsets` and runs your `Agent` with a `Tracer`.
3. Grades every check.

**It never crashes.** A setup error or an exception from the agent becomes a failed record with `stop_reason="crash"`. One broken task must not cost you the other 89 trials.

`aggregate` and `compare` are your exercises. `scripts/evals.py`:

- prints the table (with a cost column: it shows `$0.0000` until week 7 adds prices);
- saves `evals/results/<timestamp>-<provider>.json`, which is git-ignored;
- prints what changed since the previous run for that provider:

```
changes since 20260928T101500Z:
  overall: pass_rate 0.733 -> 0.8 (+0.067)
  m02-csv-to-json: pass_rate 0.333 -> 1 (+0.667)
  m02-csv-to-json: mean_tokens 5210 -> 3980 (-1230)
```

One trial, end to end:

```mermaid
sequenceDiagram
  participant CLI as scripts.evals
  participant RT as run_trial
  participant WS as temp workspace
  participant AG as Agent
  participant GR as grade
  CLI->>RT: task, model, trial n
  RT->>WS: write the task's files
  RT->>AG: Agent(tools from toolsets, tracer)
  AG->>AG: run(prompt), traced to JSONL
  AG-->>RT: RunResult
  loop each check
    RT->>GR: check, answer, workspace, judge
    GR-->>RT: CheckResult(passed, detail)
  end
  RT-->>CLI: TrialRecord (a crash is a failed record, never an exception)
  CLI->>CLI: aggregate, print table, save JSON, compare with last run
```

*The full version, with what later weeks add, is Fig 13 in [docs/architecture.md](../docs/architecture.md#fig-13-one-eval-trial).*

## 9. Exercises

| # | Function | File | Tests |
| --- | --- | --- | --- |
| 5a | `Tracer.event` | `tracer.py` | `uv run pytest tests/week5/test_tracer.py` |
| 5b | `format_timeline` | `tracer.py` | `uv run pytest tests/week5/test_timeline.py` |
| 5c | wire it in (section 5) | `loop.py` | `uv run pytest tests/week5/test_wiring.py` |
| 5d | `load_task` | `evals/tasks.py` | `uv run pytest tests/week5/test_tasks.py` |
| 5e | `grade`, `judge_verdict` | `evals/graders.py` | `uv run pytest tests/week5/test_graders.py` |
| 5f | `aggregate`, `compare` | `evals/runner.py` | `uv run pytest tests/week5/test_runner.py` |

The runner tests drive your whole agent. If one fails with a message like `NotImplementedError: Week 3 exercise: …`, the runner caught an unfinished earlier exercise and recorded it as a crash.

## 10. Try it live

**This costs money.** A full `--provider both --trials 3` run is 90 agent runs. Start small:

```bash
uv run python -m scripts.week5_demo                                           # 1 traced run + 6 eval runs, about $0.07
uv run python -m scripts.evals --tasks easy --trials 1 --provider anthropic   # 5 short runs
uv run python -m scripts.evals --tasks m05 --trials 3                         # one task, both providers
uv run python -m scripts.evals --provider both --trials 3                     # the "done when"
```

`--judge none` skips the rubric check. It then always fails, so that task will too.

Then make **one** change and run it again. For example, edit `write_file`'s description in `harnessy/tools/files.py`, or cut `DEFAULT_SYSTEM` in `evals/runner.py` down to one line. Did any number move by more than you'd expect from noise? With 3 trials, a single task's pass rate can only be 0%, 33%, 67% or 100%, so be careful what you conclude.

**Stretch.** Read 10 failed traces by hand with `scripts.trace_view`, sort the failures into groups, and write one new task for each group.

## 11. Check yourself

- `HARNESSY_IMPL=solutions uv run pytest tests/week5`
- `HARNESSY_IMPL=solutions uv run python -m scripts.evals --tasks easy --trials 1`
- `diff harnessy/evals/graders.py solutions/harnessy/evals/graders.py`

## 12. Notes for `NOTES.md`

1. Paste your first full results table. Which task failed most, and what did its trace show?
2. Which check would you trust least, and how would you find out whether the judge agrees with you?
3. Name one change you expected to help that didn't move the numbers, or one that moved them the wrong way.
