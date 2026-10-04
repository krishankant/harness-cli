# harnessy

A small agent harness you build yourself, one week at a time. It works with any model provider: Anthropic, OpenAI, or a local model through Ollama. Each week you read a short lesson, fill in the missing pieces of the code, and make the tests pass.

**What a harness is.** The model only turns text into text. The harness is everything around it: the loop that keeps calling the model, the tools it can use, what goes into its context, what it remembers, what it may do without asking, and how you measure whether it works. Two products on the same model can behave very differently because of their harness.

## The idea in one picture

The model is the brain; the harness is the body. Each week builds one organ: the loop is the heartbeat, tools are the hands, evals are the check-up, the trifecta check is the immune system. [`docs/anatomy.html`](docs/anatomy.html) explains every organ with a second everyday analogy and where the metaphor breaks (open it in a browser).

![The model is the brain, the harness is the body: each harnessy layer mapped to a body part](docs/anatomy.png)

![Every organ card: what the body part does, what the harness layer does, a second everyday analogy, and what breaks without it](docs/anatomy-organs.png)

## The weeks

**Start here:** [`LEARNING_PLAN.md`](LEARNING_PLAN.md) is the 8-week plan: what each week is about, what to read, what to build, and how you know you're done. Each week then has a hands-on lesson:

| Week | You build | Lesson |
| --- | --- | --- |
| 1 | One interface for every model provider | [`week1-model-interface.md`](lessons/week1-model-interface.md) |
| 2 | The agent loop | [`week2-agent-loop.md`](lessons/week2-agent-loop.md) |
| 3 | Tools | [`week3-tools.md`](lessons/week3-tools.md) |
| 4 | Context and memory | [`week4-context-and-memory.md`](lessons/week4-context-and-memory.md) |
| 5 | Traces and evals | [`week5-traces-and-evals.md`](lessons/week5-traces-and-evals.md) |
| 6 | Hooks, approvals, subagents and planning | [`week6-control-flow.md`](lessons/week6-control-flow.md) |
| 7 | Retries, streaming, cost limits, a sandbox, the lethal-trifecta check | [`week7-production.md`](lessons/week7-production.md) |
| 8 | Capstone: three agents on one harness | [`week8-capstone.md`](lessons/week8-capstone.md) |
| 9 (bonus) | Tools from any MCP server | [`week9-mcp.md`](lessons/week9-mcp.md) |

## Guides

Deeper reading, for when a lesson raises a question:

| If you want to know… | Read |
| --- | --- |
| What a harness is, with the whole loop on one screen and each line marked by its week | [`docs/what-is-a-harness.md`](docs/what-is-a-harness.md) (read this first) |
| Why each part exists: eight ways an agent goes wrong, run with and without the fix | [`docs/failures.md`](docs/failures.md) (`uv run python -m scripts.failure_gallery`) |
| How all the parts fit together (architecture, sequence, state and class diagrams) | [`docs/architecture.md`](docs/architecture.md), or the interactive [`architecture-archify.html`](docs/architecture-archify.html) |
| How the Anthropic and OpenAI APIs differ (messages, tool calls, stop reasons, usage, streaming) | [`docs/model-interfaces.md`](docs/model-interfaces.md) |
| What an agent run looks like on disk, read line by line | [`docs/traces.md`](docs/traces.md) |
| How an agent decides to launch a subagent | [`docs/subagents.md`](docs/subagents.md) |
| How the model plans with the todo list, from two real runs | [`docs/todo.md`](docs/todo.md) |
| How to change the loop without editing it, with six example hooks | [`docs/hooks.md`](docs/hooks.md) |
| How an injected web page can steal your data, and how harnessy stops it | [`docs/trifecta.md`](docs/trifecta.md) |
| What a skill is, and how harnessy would load one on demand | [`docs/skills.md`](docs/skills.md) |
| What the sandbox stops, what it doesn't, and how to add real isolation | [`docs/sandbox.md`](docs/sandbox.md) (`uv run python -m scripts.sandbox_demo`) |
| Which Claude Code feature matches each harnessy module | [`docs/claude-code.md`](docs/claude-code.md) |

## Setup

```bash
uv sync                  # installs anthropic, openai, python-dotenv, pyyaml and pytest
cp .env.example .env     # then fill in your keys and model names
```

`.env` is read by `load_dotenv()` at the top of each script in `scripts/`. **The tests need no keys and make no network calls.** If you use `ant auth login` for Anthropic, leave `ANTHROPIC_API_KEY` commented out, because an empty value would override your login.

## How each week works

1. Read `lessons/weekN-*.md`.
2. Run that week's tests and watch them fail: `uv run pytest tests/weekN`.
3. Fill in the functions that raise `NotImplementedError` until the tests pass. From week 3 on, this step ends with a short *wire it in* exercise in your own `loop.py`; the lesson gives the exact lines.
4. Run the week's live script to see it work against real models.
5. Write your answers to the lesson's questions in `NOTES.md`.

## What's given and what you write

| File | Week | Status |
| --- | --- | --- |
| `harnessy/types.py` | 1 | Given: the provider-neutral types (`Tool` moved here in week 3) |
| `harnessy/models/base.py` | 1 | Given: the `Model` protocol |
| `harnessy/models/anthropic.py` | 1 | **Exercise:** 4 translation functions (`AnthropicModel.complete` is given) |
| `harnessy/models/openai.py` | 1 | **Exercise:** 4 translation functions (`OpenAIModel.complete` is given) |
| `harnessy/models/scripted.py` | 2 | Given: a fake model for tests |
| `harnessy/loop.py` | 2–7 | **Exercise:** `Agent.run` and `Agent._run_tool`; weeks 3–7 add *wire it in* edits |
| `scripts/week1_compare.py` | 1 | Given: the same question on both providers |
| `scripts/week2_demo.py` | 2 | Given: the loop answering a two-tool question |
| `harnessy/tools/schema.py` | 3 | **Exercise:** `json_type`, `schema_from_function` (`@tool` and `parse_docstring` are given) |
| `harnessy/tools/registry.py` | 3 | **Exercise:** `validate_args`, `truncate`, `ToolRegistry.call` |
| `harnessy/tools/files.py` | 3 | **Exercise:** `resolve_inside` (`file_tools` is given) |
| `harnessy/tools/web.py` | 3 | Given: `http_get` |
| `harnessy/context.py` | 4 | **Exercise:** `estimate_tokens`, `clear_old_results`, `find_cut`, `Summarize.view`, `ContextManager.prepare` |
| `harnessy/memory.py` | 4 | **Exercise:** `MemoryStore.recall` (`memory_tools` is given) |
| `scripts/week3_demo.py` | 3 | Given: an agent writing and reading a file in a temp workspace |
| `scripts/week4_demo.py` | 4 | Given: a long task with and without a `ContextManager`, then memory across two runs |
| `harnessy/tracer.py` | 5 | **Exercise:** `Tracer.event`, `format_timeline` (`TraceHook` is given, for week 6) |
| `harnessy/evals/tasks.py` | 5 | **Exercise:** `load_task` (`load_tasks` is given) |
| `harnessy/evals/graders.py` | 5 | **Exercise:** `grade`, `judge_verdict` |
| `harnessy/evals/runner.py` | 5 | **Exercise:** `aggregate`, `compare` (`run_trial`, `run_evals`, `format_table` are given) |
| `evals/tasks/*.yaml` | 5 | Given: 15 eval tasks (5 easy, 5 medium, 5 hard) |
| `scripts/trace_view.py` | 5 | Given: print a trace as a timeline |
| `scripts/evals.py` | 5 | Given: run the evals, print and save the results, compare with the last run |
| `scripts/week5_demo.py` | 5 | Given: one traced run as a timeline, then 3 tasks scored before and after one change |
| `harnessy/hooks.py` | 6 | **Exercise:** `HookRunner` (`Hook`, `Block`, `StopCheck` are given) |
| `harnessy/approvals.py` | 6 | **Exercise:** `ApprovalHook.before_tool` (`terminal_approver` is given) |
| `harnessy/subagents.py` | 6 | **Exercise:** `subagent_tool` |
| `harnessy/todo.py` | 6 | **Exercise:** `TodoList.apply`, `render`, `before_model` |
| `scripts/week6_demo.py` | 6 | Given: an approval prompt, then a two-subagent task |
| `harnessy/models/retry.py` | 7 | **Exercise:** `is_retryable`, `backoff_delay`, `RetryingModel.complete` |
| `harnessy/models/openai_stream.py` | 7 | **Exercise:** `merge_openai_chunks` (each model's `stream()` is given) |
| `harnessy/streaming.py` | 7 | **Exercise:** `collect_stream`, `stream_agent` |
| `harnessy/cost.py` | 7 | **Exercise:** `price_for`, `cost_usd` (the `PRICES` table is given, checked 2026-09-28) |
| `harnessy/tools/sandbox.py` | 7 | **Exercise:** `run_command` (`run_shell` is given) |
| `harnessy/safety.py` | 7 | **Exercise:** `check_trifecta` |
| `harnessy/tools/outbox.py` | 7 | Given: a fake `send_email` that writes to a file |
| `scripts/week7_demo.py` | 7 | Given: streaming, a retried 429, a cost limit, a blocked prompt injection |
| `scripts/week8_demo.py` | 8 | Given: the research, code and data agents solving one capstone task each, with traces |
| `harnessy/mcp.py` | 9 | **Exercise:** `McpClient.request`, `connect` and `_initialize_legacy`, `list_tools`, `content_to_text`, `mcp_tools` (the stdio transport and `clean_schema` are given) |
| `scripts/mcp_notes_server.py` | 9 | Given: an example MCP server (notes), speaking both MCP eras |
| `scripts/week9_demo.py` | 9 | Given: an agent using MCP tools; `--server` connects to any stdio MCP server |
| `harnessy/tools/localweb.py` | 8 | **Exercise:** `LocalWeb.search` (serving and `web_search` are given) |
| `harnessy/tools/code.py` | 8 | **Exercise:** `edit_text` (`code_tools` is given) |
| `harnessy/tools/data.py` | 8 | **Exercise:** `query_readonly` (`data_tools`, charts are given) |
| `harnessy/evals/graders.py` | 8 | **Exercise:** `check_citations` (added to the week 5 file) |
| `harnessy/agents/` | 8 | **Exercise:** `make_agent` for research, code and data |
| `evals/corpus/` | 8 | Given: 16 pages about a fictional region, served as a local web |
| `evals/capstone/` | 8 | Given: 15 capstone tasks, 5 per agent (`scripts.evals --suite capstone`) |

## Checking against the reference solutions

`solutions/harnessy/` is a complete copy of the package. The same tests and scripts run against it when you set `HARNESSY_IMPL=solutions`:

```bash
HARNESSY_IMPL=solutions uv run pytest
HARNESSY_IMPL=solutions uv run python -m scripts.week2_demo
```

This is handled in `tests/conftest.py` and `scripts/__init__.py`. Look at the solutions after your own version passes.

## Layout

```
harnessy/            your copy: the exercises live here
solutions/harnessy/  reference copy, complete
lessons/             one lesson per week
tests/week1…week9/   offline tests (fixtures in tests/fixtures/)
evals/tasks/         eval tasks (YAML); evals/capstone/ the week 8 tasks; evals/corpus/ the local web
                     evals/results/ holds saved runs and traces (git-ignored)
scripts/             live demos (need .env)
docs/                guides, diagrams and the anatomy pages
```
