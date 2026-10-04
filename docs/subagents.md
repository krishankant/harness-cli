# Subagents: who decides, and how

Week 6 adds `spawn_subagent`. This page explains how an agent ends up launching one, which levers you have over that choice, and six ways to use it.

> **In one line:** the **model** decides to delegate, the same way it decides to call any tool. The **harness** decides whether the tool exists, what the helper may do, and whether a delegation may run.

## 1. A subagent is just a tool

There's no planner in harnessy that looks at a task and splits it. `subagent_tool(model, tools)` (`solutions/harnessy/subagents.py`) returns an ordinary `Tool`. The model sees it next to `read_file` and the others, and calls it the same way.

```mermaid
flowchart LR
  subgraph SEES["What the model sees on every step"]
    SP["System prompt"]
    H["Conversation so far"]
    T["Task"]
    TL["Tool list<br/>read_file · write_file · <b>spawn_subagent</b>"]
  end
  SEES --> D{"Model decides"}
  D -->|"enough to answer"| A["Answer<br/>stop_reason: end_turn"]
  D -->|"needs data, can do it itself"| C["Call a tool itself<br/>e.g. read_file"]
  D -->|"big, separate, or<br/>can't do it itself"| S["Call spawn_subagent<br/>with a written brief"]
  style S fill:#e8f0fe,stroke:#4a6fd8
```

This is what the model reads about the tool. It comes from the function's signature and docstring:

```json
{
  "name": "spawn_subagent",
  "description": "Hand a self-contained sub-task to a helper agent with a fresh context. It returns only its final answer.",
  "input_schema": {
    "type": "object",
    "properties": {
      "task":  {"type": "string", "description": "Everything the helper needs to know: it can't see this conversation."},
      "tools": {"type": "array", "items": {"type": "string"}, "description": "Names of the tools the helper may use (default: all of them)."}
    },
    "required": ["task"]
  }
}
```

The sentence *"it can't see this conversation"* matters. It's what makes the model write a complete brief in `task`, instead of "summarize the files we talked about".

## 2. What happens when it delegates

```mermaid
sequenceDiagram
  autonumber
  participant P as Parent agent
  participant M as Model
  participant R as Tool registry
  participant S as spawn_subagent
  participant C as Child agent (new)
  P->>M: complete(history, tools)
  M-->>P: tool_use: spawn_subagent(task="Summarize cats/…", tools=["read_file"])
  P->>R: call
  Note over R: checks the arguments<br/>timeout 600 s, not the usual 30 s
  R->>S: run
  S->>C: Agent(model, tools=[read_file], max_steps=8, hooks passed down)
  Note over C: fresh context:<br/>only the task text
  loop the child's own loop
    C->>M: complete(child history)
    M-->>C: read_file(…) or the answer
  end
  C-->>S: RunResult
  S-->>R: final text only
  R-->>P: tool_result: "Cats sleep 12–16 h…"
  P->>M: complete(history + that one summary)
```

Some details:

| | |
| --- | --- |
| **What the parent gets back** | Only the child's final text. If the child stopped early: `The subagent stopped early (max_steps). Partial answer: …` |
| **What the child starts with** | Only the `task` string, its own system prompt, the tools it was given, and the hooks passed down. |
| **A wrong tool name** | `tools=["grep"]` when there's no `grep` raises an error. The model sees `unknown tools: grep. Available: read_file` and retries. |
| **Several helpers in one turn** | If the model asks for two at once, harnessy runs them one after the other, not in parallel. |
| **Tracing** | The child isn't traced. The parent's trace shows one `tool_result` holding the summary. |
| **Cost** | The child's tokens don't reach the parent's `usage`. That's week 6's question 2. |

## 3. Why bother: the parent's context stays small

Every step resends the whole history. So whatever a helper reads but doesn't send back is paid for once, in the helper, instead of on every later step of the parent.

```mermaid
flowchart TB
  subgraph WITHOUT["Without a helper: the parent's history"]
    direction TB
    W1["task"] --> W2["read_file cats/note1.txt<br/><i>full text</i>"] --> W3["read_file cats/note2.txt<br/><i>full text</i>"] --> W4["read_file dogs/note1.txt<br/><i>full text</i>"] --> W5["read_file dogs/note2.txt<br/><i>full text</i>"] --> W6["answer"]
  end
  subgraph WITH["With two helpers: the parent's history"]
    direction TB
    H1["task"] --> H2["spawn_subagent cats/<br/><b>3-line summary</b>"] --> H3["spawn_subagent dogs/<br/><b>3-line summary</b>"] --> H4["answer"]
  end
  style WITH fill:#eef8ee,stroke:#3a9a4a
  style WITHOUT fill:#fdf0ee,stroke:#c9563c
```

With four short notes it makes little difference. With 50 log files it's the difference between a parent that fits in its context and one that doesn't.

## 4. The levers

You can't force the call through the API. The newest Claude models reject `tool_choice: any/tool`, and harnessy doesn't expose `tool_choice` anyway. You steer the model instead.

```mermaid
flowchart LR
  L1["<b>1. What the parent can't do</b><br/>no read_file → it must delegate"]:::strong
  L2["<b>2. The task's wording</b><br/>'use one helper per folder'"]:::strong
  L3["<b>3. The system prompt</b><br/>'You coordinate helpers…'"]:::mid
  L4["<b>4. The tool description</b><br/>'use when a sub-task means reading many files'"]:::weak
  L5["<b>5. Nothing</b><br/>small task + own tools →<br/>usually does it itself"]:::weak
  L1 --- L2 --- L3 --- L4 --- L5
  classDef strong fill:#dfe9ff,stroke:#3b5bcc
  classDef mid fill:#eef3ff,stroke:#6f86d6
  classDef weak fill:#f6f7fb,stroke:#9aa3c0
```

The levers on the left are the strongest. Doing nothing (the last box) is fine: for a small job, reading the file itself is cheaper than starting a whole agent, and the model usually knows that.

**To limit or stop delegation:**

| You want | Use |
| --- | --- |
| No delegation | Don't give the tool. |
| Refuse it, but let the model carry on | `ApprovalHook({"spawn_subagent": "deny"})`. The model gets a refusal and works around it. |
| A human approves each one | `ApprovalHook({"spawn_subagent": "ask"})` (the week 8 research agent). |
| Short helpers | `subagent_tool(..., max_steps=8)` |
| Helpers that follow the parent's rules | `subagent_tool(..., hooks=[guard])`. **Always do this** when the helper has a risky tool. |

## 5. Six ways to use it

The first two run as they are. Examples 3 to 6 are sketches: they leave the setup and tasks to you.

### Example 1: Splitting one job across several helpers (the week 6 demo)

```mermaid
flowchart LR
  P["Parent<br/><i>can't read files</i>"] -->|"spawn_subagent('Summarize cats/')"| C1["Helper 1<br/>read_file ×2"]
  P -->|"spawn_subagent('Summarize dogs/')"| C2["Helper 2<br/>read_file ×2"]
  C1 -->|"summary"| P
  C2 -->|"summary"| P
  P --> A["Compare in 3 sentences"]
```

```python
readers = [t for t in file_tools(root) if t.name == "read_file"]
parent = Agent(model,
    tools=[subagent_tool(model, readers)],
    system="You coordinate helpers. You can't read files yourself: give each helper one folder and ask for a summary.")
parent.run("cats/ and dogs/ each hold note1.txt and note2.txt. "
           "Use one helper per folder, then compare them in three sentences.")
```

**What makes it delegate:** levers 1, 2 and 3 together. It has no `read_file` of its own, the task says "one helper per folder", and the system prompt says it coordinates helpers.

Run it: `uv run python -m scripts.week6_demo`

### Example 2: Keeping noisy work out of the parent's context

```mermaid
flowchart LR
  P["Parent<br/>writes the report"] -->|"'when did payments first time out?'"| C["Helper<br/>reads 30 log files<br/>~30,000 tokens"]
  C -->|"5 lines"| P
  P --> R["incident.md"]
  style C fill:#fff6e0,stroke:#d19a1c
```

```python
parent = Agent(model,
    tools=[subagent_tool(model, file_tools(logs_dir), max_steps=20), *report_tools],
    system="Never read logs yourself. Send log searches to a helper and ask for at most five lines back.")
parent.run("Find when the payment service first timed out yesterday, then write incident.md.")
```

**When to use it:** whenever the work is large but the answer is small. Searching logs, reading a long spec for one limit, or scanning a codebase for one function all fit.

### Example 3: A read-only reviewer

```mermaid
flowchart LR
  P["Parent<br/>read_file · write_file"] -->|"edits code"| F[("workspace")]
  P -->|"'review my change'"| C["Reviewer<br/><b>read_file only</b><br/>fresh eyes"]
  C -->|"read"| F
  C -->|"bugs with file:line"| P
  style C fill:#eef8ee,stroke:#3a9a4a
```

```python
files = file_tools(root)
reader_only = [t for t in files if t.name == "read_file"]
parent = Agent(model,
    tools=[*files, subagent_tool(model, reader_only,
        system="You review code. Report bugs with file and line. You cannot change files.")],
    system="After you edit code, ask a helper to review it before you finish.")
```

**Why it helps:** the reviewer can't "fix" anything quietly. Because it starts with a fresh context, it also doesn't share the parent's assumptions about the code.

### Example 4: A safe helper in a risky agent (week 8 research)

```mermaid
flowchart LR
  P["Research parent<br/>web · memory · http_get"] -->|"spawn_subagent<br/><i>(ask → approved)</i>"| C["Helper<br/>web · http_get"]
  G{{"ApprovalHook<br/>http_get: ask<br/>spawn_subagent: ask"}}
  G -.guards.-> P
  G -.<b>same guard</b>.-> C
  C -->|"http_get"| G
  style G fill:#fdf0ee,stroke:#c9563c
```

```python
guard = ApprovalHook({"http_get": "ask", "spawn_subagent": "ask"}, approver=research_approver(web))
tools = [*readers, *memory_tools(store),
         subagent_tool(model, readers, hooks=[guard], max_steps=8)]
Agent(model, tools=tools, hooks=[guard], ...)
```

**The point is `hooks=[guard]` on the helper.** Without it, a parent whose `http_get` is guarded could hand the same request to a helper with no guard and get around its own policy. `spawn_subagent` also inherits `http_get`'s trifecta tags, so week 7's check sees the risk too.

### Example 5: A cheaper model for the helpers

```mermaid
flowchart LR
  P["Parent: Claude Opus 5<br/>plans and combines"] -->|"bulk reading"| C1["Helper: Claude Haiku 4.5"]
  P -->|"bulk reading"| C2["Helper: Claude Haiku 4.5"]
  C1 --> P
  C2 --> P
```

```python
cheap = AnthropicModel("claude-haiku-4-5")
parent = Agent(AnthropicModel("claude-opus-5"), tools=[subagent_tool(cheap, readers)], ...)
```

`subagent_tool` takes its own `model`, so a strong model can plan while a cheaper one does the reading.

### Example 6: When *your code* decides: a workflow, not an agent

If you already know the split ("summarize each of these 20 files"), the model doesn't need to decide anything.

```mermaid
flowchart LR
  CODE["Your Python<br/>for p in paths"] --> A1["Agent: summarize p1"]
  CODE --> A2["Agent: summarize p2"]
  CODE --> A3["… p20"]
  A1 & A2 & A3 --> J["Agent: combine the summaries"]
  style CODE fill:#f3eefc,stroke:#7a55c2
```

```python
summaries = {p: Agent(model, tools=readers, system=SUBAGENT_SYSTEM).run(f"Summarize {p}.").final_text
             for p in paths}
final = Agent(model, tools=[]).run("Combine these summaries:\n" + json.dumps(summaries))
```

**What it gets you:** this is cheaper and gives the same split every time. You can also run the children in parallel with a thread pool.

## 6. Should this be a subagent?

```mermaid
flowchart TD
  Q1{"Do you know the split<br/>before the run?"} -->|yes| WF["Your code calls the agents<br/>(example 6)"]
  Q1 -->|no| Q2{"Will the work fill the<br/>parent's context with text<br/>it won't need again?"}
  Q2 -->|yes| SA["spawn_subagent<br/>(examples 1, 2)"]
  Q2 -->|no| Q3{"Does the sub-task need<br/>different permissions<br/>or a fresh view?"}
  Q3 -->|yes| SA2["spawn_subagent with<br/>restricted tools (examples 3, 4)"]
  Q3 -->|no| DIRECT["Give the parent the tool<br/>directly: cheaper"]
  style DIRECT fill:#eef8ee,stroke:#3a9a4a
  style WF fill:#f3eefc,stroke:#7a55c2
  style SA fill:#e8f0fe,stroke:#4a6fd8
  style SA2 fill:#e8f0fe,stroke:#4a6fd8
```

**The cost:**
- Every helper is a whole agent run, with its own system prompt, tool definitions and steps.
- Anthropic measured multi-agent research at about 15× the tokens of a plain chat.

**When to skip it:** if the task is small, or the parent needs the raw details later (exact file contents to edit, say), delegation costs more and loses information.

## See also

- `lessons/week6-control-flow.md`, section 6, and exercise 6c (`tests/week6/test_subagents.py`)
- [Fig 10 in `docs/architecture.md`](architecture.md#fig-10-subagents)
- `scripts/week6_demo.py`, part 2
- [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (Anthropic)
