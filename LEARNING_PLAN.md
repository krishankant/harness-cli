# Harness Engineering: 8-Week Learning Plan

In 8 weeks at about 5 hours a week, you will write **harnessy**, a small Python agent harness that works with any model provider. Then you will prove it is general by running three different agents on it.

**What a harness is.** The model only turns text into text. The harness is everything around it:

- the loop that keeps calling the model;
- the tools it can use;
- what goes into its context;
- what it remembers;
- what it may do without asking;
- how you measure whether it works.

Two products on the same model can behave very differently because of their harness. That is why "harness engineering" became its own discipline.

## How to use this with the repo

This repo is the course. For each week:

1. **Read the section for that week below.** It gives the idea, the readings and what to build.
2. **Open the lesson** in [`lessons/`](lessons/). It walks through the code, the exercises and exactly what to add to your loop.
3. **Make the tests pass:** `uv run pytest tests/weekN`. The exercises are the functions in `harnessy/` that raise `NotImplementedError`.
4. **Run the week's live script** in `scripts/`.
5. **Write your notes** in `NOTES.md`.

`solutions/harnessy/` has the reference answers: `HARNESSY_IMPL=solutions uv run pytest` runs the same tests against them. [`docs/architecture.md`](docs/architecture.md) has diagrams of how every part fits together. Start with the [README](README.md) for setup.

| Week | Lesson | Tests | Try it live |
| --- | --- | --- | --- |
| 1 | [One interface for every model](lessons/week1-model-interface.md) | `tests/week1` | `uv run python -m scripts.week1_compare` |
| 2 | [The agent loop](lessons/week2-agent-loop.md) | `tests/week2` | `uv run python -m scripts.week2_demo` |
| 3 | [Tools](lessons/week3-tools.md) | `tests/week3` | `uv run python -m scripts.week3_demo` |
| 4 | [Context and memory](lessons/week4-context-and-memory.md) | `tests/week4` | `uv run python -m scripts.week4_demo` |
| 5 | [Traces and evals](lessons/week5-traces-and-evals.md) | `tests/week5` | `uv run python -m scripts.evals --tasks easy --trials 1` |
| 6 | [Control flow](lessons/week6-control-flow.md) | `tests/week6` | `uv run python -m scripts.week6_demo` |
| 7 | [Production concerns](lessons/week7-production.md) | `tests/week7` | `uv run python -m scripts.week7_demo` |
| 8 | [Capstone](lessons/week8-capstone.md) | `tests/week8` | `uv run python -m scripts.evals --suite capstone --trials 1` |
| 9 (bonus) | [Tools from anywhere with MCP](lessons/week9-mcp.md) | `tests/week9` | `uv run python -m scripts.week9_demo` |

**How to use this plan.** Work through one week at a time, in order: each week adds a layer the next one depends on. Every week has the same parts:

- **Why it matters:** the one idea to take away
- **Read:** 2 or 3 resources, about 1.5 hours
- **Build:** a checklist for your repo, about 3 hours
- **Done when:** a test you can run to prove the week is finished
- **Stretch:** optional, if you have time left

**Weekly rhythm (about 5 hours).** Read early in the week. Build in two or three sessions. Finish with 20 minutes writing notes in `NOTES.md`: what surprised you and what you would change. Those notes become the write-up in week 8.

**Rules for the project.** No agent framework inside harnessy (LangChain, LangGraph, CrewAI and similar). You may use the official provider SDKs and the standard library. You'll read framework source code to compare designs, but you won't import it.

## Before week 1: setup (about 1 hour)

You need Python 3.11+ and keys for two model providers. A local model is optional, but it makes the "any provider" claim real and costs nothing to run.

- [ ] Python 3.11+ with `uv`, then `uv sync` in this repo (installs the SDKs, `pyyaml` and `pytest`)
- [ ] An Anthropic API key and an OpenAI API key, each with a small spending limit (around $10 is plenty for 8 weeks)
- [ ] Optional: [Ollama](https://docs.ollama.com/api/openai-compatibility) with a small tool-calling model. It serves an OpenAI-compatible API at `localhost:11434/v1`
- [ ] Keys in a `.env` file loaded by the code (`cp .env.example .env`), never in your shell rc file, because non-interactive runs don't read it
- [ ] Run `uv run pytest tests/week1` and see the exercises fail. That's your starting point.

**Assumed background.** You can write Python classes and tests, and call a REST API. You don't need any machine-learning background.

## What you're building

By week 8, harnessy has seven parts. The loop is the only one that knows about all the others, and each of the rest can be swapped out without touching the loop. See [`docs/architecture.md`](docs/architecture.md) (Fig 1) for the picture.

The agent you write in week 8 is just configuration: a prompt, a list of tools and some limits. Everything else is the harness. Keep that boundary sharp. If agent-specific logic creeps into the loop, the "generic" test in week 8 will expose it.

## Week 1: One interface for every model

**Why it matters.** Providers disagree on message formats: roles, where the system prompt goes, how tool calls and tool results are shaped, and what a stop reason is called. If those differences leak past one layer, your harness is tied to one provider for good.

**Read**

- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (Anthropic). The vocabulary: workflows versus agents, and "start with the simplest thing".
- [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works) (Claude docs) and OpenAI's [function calling guide](https://platform.openai.com/docs/guides/function-calling). Read them side by side and list every difference.
- [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) (Ollama). This is how a local model joins through the OpenAI-style adapter.

**Build**

- [ ] Define your own types: `Message`, `ToolCall`, `ToolResult`, `ModelResponse` (text, tool calls, stop reason, token usage)
- [ ] A `Model` protocol with one method: `complete(messages, tools, system) -> ModelResponse`
- [ ] An `AnthropicModel` and an `OpenAIModel` adapter that translate to and from your types
- [ ] Map each provider's stop reasons onto your own small set: `end_turn`, `tool_use`, `max_tokens`, `refused`, `error`
- [ ] Record token usage on every response. You'll need it for budgets and cost in later weeks

**Done when.** One script sends the same conversation, including a fake tool call and result, to both providers and gets back the same `ModelResponse` shape. Unit tests cover the translation both ways using recorded API responses, with no network calls.

**Stretch.** Add the Ollama adapter by reusing `OpenAIModel` with a different base URL, and write down what broke.

## Week 2: The agent loop

**Why it matters.** An agent is a model running in a loop with tools. The loop is short, but every decision in it affects reliability: when to stop, what to do with a failed tool, and how to stop a model that keeps looping.

**Read**

- [How to Build an Agent](https://ampcode.com/notes/how-to-build-an-agent) (Thorsten Ball, Amp). A working code-editing agent in under 400 lines of Go. Port the idea, not the code.
- [ReAct: Synergizing Reasoning and Acting](https://arxiv.org/abs/2210.03629) (Yao et al., 2022). The paper behind think, act, observe. Read the introduction and figures 1–2.
- The agent class in [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent/). About 100 lines of Python that score over 70% on SWE-bench Verified. Notice how little is there.

**Build**

- [ ] `Agent.run(task) -> RunResult`. Call the model, run any tool calls, append the results, and repeat until `end_turn`
- [ ] Three stop conditions besides success: `max_steps`, `max_tokens_total` and wall-clock `timeout`. Each one returns a clear reason, never an exception
- [ ] Run several tool calls from one model turn, and return every result in the same order
- [ ] Two toy tools, `add(a, b)` and `get_time()`, hand-written for now (the registry comes in week 3)
- [ ] A verbose option that prints each step as it happens

**Done when.** "What is 17 + 25, and what time is it?" finishes in 2–3 steps on both providers. A test with a fake model that never stops ends at `max_steps` with the reason recorded.

**Stretch.** Build a fake `ScriptedModel` that replays a fixed list of responses. You'll use it to test the loop without spending tokens for the rest of the plan. (In this repo it's given, in `harnessy/models/scripted.py`.)

## Week 3: Tools

**Why it matters.** The model only knows a tool through its name, description and parameter schema, so those are prompts. Tool design, including what a tool returns when it fails, is often where an agent gains or loses the most quality.

**Read**

- [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents) (Anthropic). Namespacing, returning meaningful context, token-efficient responses, and testing tools with evals.
- [SWE-agent: Agent-Computer Interfaces](https://arxiv.org/abs/2405.15793) (Yang et al., 2024). Sections 2–3 show that changing only the tool interface changed benchmark scores a lot.

**Build**

- [ ] A `@tool` decorator that builds the JSON schema from type hints and the docstring (using `inspect`)
- [ ] A `ToolRegistry` that checks arguments against the schema before calling the function
- [ ] Return failures as tool results the model can read (bad arguments, exceptions, timeouts), with a hint on how to fix the call. Never crash the loop
- [ ] Cap each tool result's size and say it was cut off, for example "showing the first 4,000 of 51,200 characters"
- [ ] Three real tools: `read_file`, `write_file` and `http_get`

**Done when.** You can register a plain Python function with one decorator and no hand-written schema. A test sends bad arguments and checks that the model gets a readable error and fixes its call on the next step.

**Stretch.** Try two descriptions for the same tool (short and detailed) and write down which one gets called correctly more often. You'll turn this into a real eval in week 5.

## Week 4: Context and memory

**Why it matters.** The context window is the agent's only working memory, and models get worse as it fills up. Deciding what goes in, what gets dropped and what gets summarized is the core skill of harness engineering.

**Read**

- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (Anthropic). Context as a limited budget, loading data just in time, compaction, and note-taking.
- [Context Engineering for AI Agents: Lessons from Building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus). Keeping the prompt prefix stable so the cache keeps hitting, masking tools instead of removing them, and using the file system as memory.
- [Context Rot](https://www.trychroma.com/research/context-rot) (Chroma, 2025). Measurements across 18 models showing quality drops as the input gets longer.

**Build**

- [ ] A `ContextManager` that builds what the model sees from the full history and counts tokens (a rough estimate of 4 characters per token is fine)
- [ ] Two strategies behind one interface: `DropOldest` (keep the task and the most recent turns) and `Summarize` (the model compacts old turns into a note)
- [ ] Clear old tool results: once a large result has been used, replace it with a one-line stub
- [ ] `MemoryStore`: a small file-backed key-value store and two tools, `remember(key, text)` and `recall(query)`, that persist between runs
- [ ] Keep the system prompt and tool list byte-for-byte stable within a run, so prompt caching works

**Done when.** A 30-step scripted run stays under a budget you set (for example 8,000 tokens) and still finishes the task. A second run recalls a fact the first run stored.

**Stretch.** Turn on prompt caching for the Anthropic adapter and log the cache-hit tokens per step.

## Week 5: Tracing and evals

**Why it matters.** Without evals, every change to a prompt or tool is a guess. Agents are random, so one good run proves little. You need many runs, graded on the end result, and traces so you can see why each run failed.

**Read**

- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) (Anthropic, January 2026). The vocabulary: a task versus a trial, and a transcript versus an outcome. Grade the outcome first, then use model judges calibrated against humans.
- [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/) (Hamel Husain). Look at your data first, analyze errors, then write evals that target the failures you find.

**Build**

- [ ] A `Tracer` that writes one JSON line per event (model call, tool result, stop), with tokens, time and step number
- [ ] A small trace viewer: a script that prints one run as a readable timeline
- [ ] 15 eval tasks in YAML, each with an input, a way to check the end result and a step limit. Mix easy, medium and hard
- [ ] Two kinds of grader: code checks (a file exists, the answer matches, the JSON is valid) and one model-graded rubric
- [ ] A runner that does N trials per task and reports the pass rate, mean steps and mean tokens, saved so you can compare with later runs (cost joins in week 7)

**Done when.** `uv run python -m scripts.evals --provider both --trials 3` prints a table for both providers. Changing one tool description visibly moves at least one number.

**Stretch.** Read 10 failed traces by hand, group the failures into types, and write one new task for each type.

## Week 6: Control flow: hooks, approvals, subagents, planning

**Why it matters.** Most production agents are not purely autonomous. They mix fixed code with a few points where the model decides. Hooks, human approval and subagents are how you keep control without forking the loop.

**Read**

- [12-Factor Agents](https://github.com/humanlayer/12-factor-agents) (HumanLayer). Owning your control flow, contacting humans through tool calls, and small focused agents.
- [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (Anthropic). Orchestrator and workers, and why subagents help: each gets its own clean context. Note the cost: about 15× the tokens of a normal chat.
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (Anthropic). Progress files and a setup agent that let work continue across context windows.

**Build**

- [ ] Hook points: `before_model`, `after_model`, `before_tool`, `after_tool`, `on_stop`. A hook can observe, change the call or block it
- [ ] An approval policy for each tool (`allow`, `ask` or `deny`), with the "ask" step going through a pluggable approver (the terminal for now)
- [ ] A `spawn_subagent(task, tools)` tool that runs a child `Agent` with a fresh context and returns only its final answer
- [ ] A `todo` tool (add, complete, list) whose state goes back into the context each turn

**Done when.** A task that needs a risky tool stops for your approval and continues after you say yes. A research-style task splits into two subagents, and the parent's context shows only their summaries.

**Stretch.** Make the stop decision a hook: `on_stop` can reject "done" if a check fails, for example the tests don't pass yet, and send the agent back to work.

## Week 7: Production concerns

**Why it matters.** A demo agent fails in ways a production agent can't: API errors, runaway costs, tool calls that hang, and web pages that contain instructions aimed at the model. Most of these are harness problems, not model problems.

**Read**

- [The lethal trifecta for AI agents](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) (Simon Willison). Private data plus untrusted content plus a way to send data out means data can be stolen. The defense is architectural, not a better prompt.
- [A practical guide to building agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) (OpenAI). Read the sections on guardrails and human intervention.

**Build**

- [ ] Retries with exponential backoff and jitter for rate limits and 5xx errors, as one wrapper around any model. Never retry a tool that has side effects without checking first
- [ ] Streaming: `Agent.stream(task)` yields text and events as they arrive
- [ ] A cost meter: a price table per model, a running total per run, and a hard `max_cost_usd` stop
- [ ] Tool sandboxing: run shell or code tools in a subprocess with a timeout and a temporary working folder, with Docker as a stretch goal
- [ ] Tag each tool as `private_data`, `untrusted_input` or `external_send`. Refuse any run configuration that turns on all three without an approval hook

**Done when.** A run survives a simulated 429 error and a hung tool. A prompt-injection test task (a web page telling the agent to email out your data) gets blocked by the policy instead of relying on the model to refuse.

**Stretch.** Add a second eval set just for failures and attacks, and run it in CI along with your normal evals.

## Week 8: Capstone: prove it's generic

**Why it matters.** A harness is only generic if very different agents run on it without changes to the harness. Build three agents that use different tools and succeed in different ways. Whatever you had to change in harnessy is what you learned.

**Build the three agents.** Each one is only configuration: a system prompt, tools and limits.

| Agent | Tools | Eval tasks (5 each) | How success is checked |
| --- | --- | --- | --- |
| Research | `web_search`, `http_get`, `spawn_subagent`, `remember` | Answer a factual question with cited URLs | The answer is correct and every cited URL loads and supports it |
| Files / code | `read_file`, `write_file`, `edit_file`, `run_tests` (sandboxed) | Fix a bug in a small repo | The repo's tests pass |
| Data | `list_tables`, `run_sql` (read-only SQLite), `plot_query` | Answer a question about a sample database | The number matches a known answer |

(In this repo, the research agent searches a local mini-web of fictional pages so the evals are offline and repeatable. The data agent charts a query result with `plot_query`; the original plan said `plot_csv`, but a read-only agent has no CSV to plot.)

**Then compare.** Read these codebases for an hour each, and for every part of your architecture, note how each one handles it:

- [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent/): the minimal end of the spectrum
- [LangGraph](https://github.com/langchain-ai/langgraph): the loop as an explicit state graph
- [OpenAI Agents SDK](https://github.com/openai/openai-agents-python): handoffs, guardrails and tracing as built-in features

**Write-up (about 1 page in `NOTES.md`).** Which harness changes did each agent force? Which parts were truly reusable? What would you change if you started again? Include each agent's pass rate on both providers.

**Done when.** All three agents run from the same harnessy version, each passes at least 3 of its 5 tasks, and the write-up is done.

**Stretch.** Read OpenAI's [Harness engineering](https://openai.com/index/harness-engineering/) post on building a product almost entirely with agents. Map its ideas (making things legible to the agent, enforcing rules mechanically, fast feedback loops) onto your own design.

## Week 9 (bonus): Tools from anywhere with MCP

**Why it matters.** The Model Context Protocol (MCP) lets anyone publish tools once, for every agent: a server offers tools as a name, a description and a JSON Schema, which is exactly what your registry already speaks. Connecting to MCP turns a whole ecosystem of servers into harnessy tools, and it tests the week 3 design: if the harness is generic, MCP tools need no loop changes at all.

**Read**

- [MCP specification](https://modelcontextprotocol.io/specification/2026-07-28): the overview, then [versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning), [stdio](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio) and [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

**Build**

- [ ] A JSON-RPC client over stdio: one message per line, responses matched to requests by id, timeouts, clean shutdown
- [ ] Era detection: probe `server/discover`; modern servers get per-request `_meta`, legacy servers get the `initialize` handshake
- [ ] `tools/list` with paging, and `tools/call` with every content type turned into text for the model
- [ ] `mcp_tools`: each MCP tool becomes a harnessy `Tool`, tagged with all three trifecta legs unless you trust the server

**Done when.** An agent saves and searches notes through the bundled MCP server, and connects to at least one real MCP server (`--server`), whatever era it speaks.

**Stretch.** Streamable HTTP for remote servers, resources as a read-only tool, or answering `input_required` results with the week 6 approver.

## Guidelines while you build

These ten rules come from the readings above. Check your code against them at the end of each week.

1. **Start with the simplest thing that works.** Add a part only when an eval or trace shows you need it.
2. **Keep provider details inside the adapters.** If `anthropic` or `openai` is imported outside `models/`, fix it.
3. **The model sees text, so treat tool names, descriptions, errors and truncation notes as prompts.** Write them for the model, not for yourself.
4. **Return failures to the model; don't raise them.** A readable error lets the model correct itself. An exception ends the run.
5. **Every loop needs a limit.** Steps, tokens, time and money: always set all four.
6. **Context is a budget.** Load data when it's needed, clear results once they've been used, and keep the prompt prefix stable so the cache keeps hitting.
7. **Record everything, then read the traces.** Most fixes come from reading 10 failed runs, not from guessing.
8. **Grade the end result, not the path the agent took.** Check what changed in the world first, and use model judges only where code can't check.
9. **Enforce safety in code, not in prompts.** Permissions, sandboxes and the lethal-trifecta check live in the harness.
10. **Every harness feature makes up for something the model can't do yet.** Write down the reason for each one, and remove it when newer models no longer need it.

## All resources

Every link used in the weeks above, grouped by type, plus two optional extras for going further. Links checked on 27 September 2026.

| Resource | Type | Week |
| --- | --- | --- |
| [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (Anthropic) | Guide | 1 |
| [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works) (Claude docs) | API docs | 1 |
| [Function calling](https://platform.openai.com/docs/guides/function-calling) (OpenAI docs) | API docs | 1 |
| [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) (Ollama docs) | API docs | 1 |
| [How to Build an Agent](https://ampcode.com/notes/how-to-build-an-agent) (Thorsten Ball) | Tutorial | 2 |
| [ReAct](https://arxiv.org/abs/2210.03629) (Yao et al., 2022) | Paper | 2 |
| [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent/) | Source code | 2, 8 |
| [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents) (Anthropic) | Guide | 3 |
| [SWE-agent: Agent-Computer Interfaces](https://arxiv.org/abs/2405.15793) (Yang et al., 2024) | Paper | 3 |
| [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (Anthropic) | Guide | 4 |
| [Lessons from Building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | Case study | 4 |
| [Context Rot](https://www.trychroma.com/research/context-rot) (Chroma, 2025) | Research | 4 |
| [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) (Anthropic, Jan 2026) | Guide | 5 |
| [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/) (Hamel Husain) | Essay | 5 |
| [12-Factor Agents](https://github.com/humanlayer/12-factor-agents) (HumanLayer) | Principles | 6 |
| [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (Anthropic, Jun 2025) | Case study | 6 |
| [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (Anthropic) | Case study | 6 |
| [The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) (Simon Willison) | Security | 7 |
| [A practical guide to building agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) (OpenAI) | Guide (PDF) | 7 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Source code | 8 |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Source code | 8 |
| [Harness engineering](https://openai.com/index/harness-engineering/) (OpenAI) | Case study | 8 |
| [Context engineering cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools) (Claude) | Notebook | Extra: 4 |
| [awesome-harness-engineering](https://github.com/walkinglabs/awesome-harness-engineering) | Link list | Extra: after week 8 |

## Progress tracker

Copy this into your `NOTES.md` and update it when you finish each week's "Done when" test. Put your eval pass rate in the notes from week 5 on.

| Week | Milestone | Status | Notes |
| --- | --- | --- | --- |
| 0 | Setup: repo, keys, `uv sync` | Not started | |
| 1 | Same conversation works on 2 providers | Not started | |
| 2 | Loop stops correctly on every limit | Not started | |
| 3 | Decorator-built tools; model recovers from errors | Not started | |
| 4 | 30-step run fits a token budget; memory persists | Not started | |
| 5 | Eval table for both providers | Not started | |
| 6 | Approval pauses a run; subagents return summaries | Not started | |
| 7 | Survives 429s and a hung tool; injection blocked | Not started | |
| 8 | 3 agents, 3 of 5 tasks passed each, write-up done | Not started | |
| 9 | Agent uses MCP tools; one real server connected | Not started | |
