# harness-cli Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `harness` command that runs harnessy as an interactive, Claude Code/Codex-style
coding agent in the terminal, plus a scriptable `harness -p` mode.

**Architecture:** A new package `harness_cli/` on top of the unchanged-in-spirit `harnessy/`
library. A worker-thread engine turns one prompt into a stream of events. The REPL and the
headless runner both consume those events. Permissions, the sandbox, sessions and slash
commands are small separate modules.

**Tech Stack:** Python 3.11+, standard library only (argparse, readline, json, fnmatch,
threading, queue), plus harnessy's existing dependencies (anthropic, openai, python-dotenv,
pyyaml). uv for environments, pytest for tests, hatchling to build the `harness` script.

**Spec:** [`docs/cli/design.md`](design.md) (why this approach: [`approaches.md`](approaches.md))

## Global Constraints

- Python `>=3.11`; no new runtime dependencies.
- Console script name: `harness`; also runnable as `python -m harness_cli`.
- User config root: `~/.harness/` (override with `HARNESS_HOME`, which tests use).
- Project config folder: `<workspace>/.harness/`; instruction files read in this order:
  `HARNESS.md`, `AGENTS.md`, `CLAUDE.md`.
- Every test runs without API keys or network (`ScriptedModel`).
- The existing harnessy test suite (325 tests) stays green.
- The lethal-trifecta check stays enabled in every mode.
- Every dependency or config key a task adds names the code that consumes it (below, in
  each task's *Interfaces*).

## Review Focus

1. **A workspace path with spaces, or one reached through a symlink** (macOS `/tmp` →
   `/private/tmp`): the Seatbelt profile and file confinement must still match. Test in
   Task 3 (`test_sandbox_workspace_with_space`).
2. **Binary or non-UTF-8 files** hit by `search_files` / `read_file`: skip or replace, never
   crash the tool. Test in Task 3 (`test_search_skips_binary`).
3. **A corrupt or half-written session file** (the CLI was killed mid-write): loading skips
   the bad line and keeps the rest. Test in Task 6 (`test_load_skips_corrupt_line`).
4. **Ctrl-C or EOF while an approval prompt is open**: treated as "no", the turn is
   cancelled, the CLI keeps running. Test in Task 7 (`test_prompt_eof_is_no`).
5. **Output is not a terminal** (piped into a file, `NO_COLOR` set): no ANSI codes in the
   output. Test in Task 8 (`test_no_color_when_not_tty`).

---

### Task 1: Multi-turn history in the harnessy loop

**Files:**
- Modify: `harnessy/loop.py` (`Agent.run`, `Agent.stream`)
- Modify: `harnessy/streaming.py` (`stream_agent`)
- Test: `tests/cli/test_history.py`

**Interfaces:**
- Produces: `Agent.run(task: str, history: list[Message] | None = None) -> RunResult`;
  `Agent.stream(task, history=None)`; `stream_agent(agent, task, history=None)`.
  `RunResult.messages` holds the whole conversation, history included.
- Consumed by: `harness_cli/engine.py` (Task 5).

- [ ] Write tests: a second run with `history=first.messages` sends the earlier turns to the
  model (`ScriptedModel.calls[-1].messages`) and its `RunResult.messages` starts with them;
  `history=None` behaves exactly as before.
- [ ] Implement: `messages = [*(history or []), Message(role="user", text=task)]`; pass
  `history` through `stream`/`stream_agent`.
- [ ] Run `uv run pytest -q` — all 325 old tests plus the new ones pass. Commit.

### Task 2: Settings and providers

**Files:**
- Create: `harness_cli/config.py`, `harness_cli/providers.py`
- Test: `tests/cli/test_config.py`

**Interfaces:**
- Produces: `Settings` dataclass (`provider`, `model`, `permission_mode`, `allow`, `deny`,
  `sandbox`, `max_steps`, `max_cost_usd`, `shell_timeout_s`, `context_budget_tokens`,
  `mcp_servers`, `system_prompt`, `append_system_prompt`); `harness_home() -> Path`;
  `load_settings(workspace: Path, overrides: dict) -> Settings`; `ConfigError`.
  `make_model(provider: str, model: str | None) -> Model`.
- Config keys and their consumers: `provider`/`model` → `providers.make_model`;
  `permission_mode`/`permissions.allow`/`permissions.deny` → `permissions.build_permissions`;
  `sandbox`, `shell_timeout_s` → `tools.build_tools`; `max_steps`, `max_cost_usd`,
  `context_budget_tokens` → `engine.Engine`; `mcpServers` → `tools.start_mcp`;
  `system_prompt`, `append_system_prompt` → `instructions.build_system_prompt`.

- [ ] Tests: defaults when no files exist; project file overrides user file; flags override
  both; `permissions.allow` lists are concatenated (user + project), scalars are replaced;
  invalid JSON raises `ConfigError` naming the file; unknown `permission_mode` raises.
- [ ] Implement `config.py`; `providers.py` maps `anthropic`/`openai`/`ollama` (OpenAI client
  with `http://localhost:11434/v1`) and wraps in `RetryingModel`.
- [ ] Run tests, commit.

### Task 3: Tools and sandbox

**Files:**
- Create: `harness_cli/sandbox.py`, `harness_cli/tools.py`, `harness_cli/instructions.py`
- Test: `tests/cli/test_tools.py`, `tests/cli/test_sandbox.py`, `tests/cli/test_instructions.py`

**Interfaces:**
- Produces: `seatbelt_profile(workspace: Path) -> str`; `sandbox_available() -> bool`;
  `run_sandboxed(command: str, workspace: Path, timeout_s: float, mode: str) -> CommandResult`;
  `build_tools(workspace, settings, todo: TodoList, model, approval_hook) -> list[Tool]`;
  `KIND: dict[str, str]` (tool name → `read`/`edit`/`execute`/`agent`);
  `start_mcp(servers: dict, ) -> tuple[list[Tool], list[McpClient], list[str]]` (tools,
  clients to close, error lines);
  `build_system_prompt(workspace: Path, settings: Settings, tool_names) -> str`.
- Consumes: `harnessy.tools.code.code_tools`, `harnessy.tools.sandbox.run_command`,
  `harnessy.subagents.subagent_tool`, `harnessy.mcp`.

- [ ] Tests: `list_files` respects a glob and skips `.git`, `.venv`, `node_modules`;
  `search_files` finds a regex with `path:line: text` and skips binary files
  (`test_search_skips_binary`); file tools refuse `../outside`; `run_shell` returns exit code
  and output; on macOS the Seatbelt sandbox blocks a write outside the workspace and allows
  one inside, also for a workspace path containing a space
  (`test_sandbox_workspace_with_space`); `build_system_prompt` includes `HARNESS.md` then
  `AGENTS.md`, and the append prompt last.
- [ ] Implement. Seatbelt profile: allow default; deny network; deny writes except the
  workspace, temp folders and `/dev`; deny reads of `~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.harness`. Resolve the workspace path (symlinks) before putting it in the profile.
- [ ] Run tests, commit.

### Task 4: Permissions

**Files:**
- Create: `harness_cli/permissions.py`
- Test: `tests/cli/test_permissions.py`

**Interfaces:**
- Produces: `MODES = ("default", "accept-edits", "plan", "bypass")`;
  `Rule.parse(text) -> Rule`, `Rule.matches(call: ToolCall) -> bool`;
  `policy_for(mode: str, tool_names, allow_rules) -> dict[str, Decision]`;
  `Approver(mode, allow, deny, ask_human: Callable[[ToolCall], str] | None)` callable as
  `approver(call) -> bool`, with `.always: set[str]`;
  `build_permissions(mode, tool_names, allow, deny, ask_human) -> tuple[ApprovalHook, Approver]`;
  `Approver.set_mode(mode)` and `ApprovalHook.policy` refreshed by `apply_mode(hook, approver, mode, tool_names)`.
- Consumed by: `engine.Engine` (Task 5), `/mode` in `commands.py` (Task 7).

- [ ] Tests: the mode table from the spec for every kind; `Rule("run_shell(git *)")` matches
  `git status` and not `rm`; deny beats allow; a bare-name allow becomes `allow` in the
  policy; the human answer `a` adds to `.always`; no `ask_human` (headless) → declined;
  bypass mode passes `check_trifecta`.
- [ ] Implement, run tests, commit.

### Task 5: Engine

**Files:**
- Create: `harness_cli/engine.py`
- Test: `tests/cli/test_engine.py`

**Interfaces:**
- Produces: events `TextDelta`, `ToolStart`, `ToolEnd` (re-exported from
  `harnessy.streaming`), `ApprovalRequest(call, reply: queue.Queue[bool])`, `Done(result)`;
  `Engine(model, tools, system, hooks, max_steps, max_cost_usd, context_budget_tokens)`;
  `Engine.turn(prompt: str, history: list[Message]) -> Iterator[Event]`;
  `Engine.cancel()`; `Engine.ask_via_queue(call) -> bool` (the approver hook-up);
  `Engine.usage`, `Engine.cost_usd` running totals.
- Consumes: Task 1 `Agent.run(history=...)`, Task 4 `Approver`.

- [ ] Tests: a two-turn conversation keeps history; an approval round trip — the consumer
  receives `ApprovalRequest`, puts `True`, and the tool runs; putting `False` gives the model
  an error result; `cancel()` during a turn ends it with stop reason `blocked`; usage and cost
  accumulate across turns.
- [ ] Implement with one worker thread per turn and a `CancelHook` (blocks `before_model` and
  `before_tool` once cancelled). Commit.

### Task 6: Sessions

**Files:**
- Create: `harness_cli/session.py`
- Test: `tests/cli/test_session.py`

**Interfaces:**
- Produces: `Session(id, workspace, messages, usage, cost_usd, provider, model)`;
  `Session.new(workspace, provider, model)`; `session.save()` (rewrites atomically);
  `load(workspace, id_or_prefix) -> Session`; `latest(workspace) -> Session | None`;
  `list_sessions(workspace) -> list[SessionInfo]`; `message_from_json(dict) -> Message`.
- Consumed by: `repl.py`, `headless.py`, `/sessions`, `/resume`.

- [ ] Tests: save/load round trip keeps text, tool calls, tool results and `ProviderRaw`;
  `latest` picks the newest; a prefix resumes; an ambiguous prefix raises; a corrupt line is
  skipped (`test_load_skips_corrupt_line`); sessions of another folder are not listed.
- [ ] Implement (write to a temp file, then `os.replace`). Commit.

### Task 7: Commands, rendering, REPL

**Files:**
- Create: `harness_cli/commands.py`, `harness_cli/render.py`, `harness_cli/repl.py`
- Test: `tests/cli/test_commands.py`, `tests/cli/test_repl.py`

**Interfaces:**
- Produces: `parse_input(line) -> tuple[kind, name, args]` (`slash`, `shell`, `prompt`);
  `expand_mentions(text, workspace) -> str`; `load_custom_commands(workspace) -> dict[str, CustomCommand]`;
  `CommandContext` and `COMMANDS` registry (`/help`, `/clear`, `/compact`, `/cost`, `/model`,
  `/mode`, `/tools`, `/todo`, `/sessions`, `/resume`, `/init`, `/exit`);
  `Renderer(out, color: bool)` with `text`, `tool_start`, `tool_end`, `ask(call) -> str`,
  `info`, `error`; `run_repl(app, input_fn=input, out=sys.stdout) -> int`.

- [ ] Tests: parsing of `/cmd args`, `!ls`, plain text; `@README.md` is replaced by a
  fenced block with the file's contents and a missing file is left alone; custom command
  `$ARGUMENTS` substitution and the `description:` line; a scripted REPL session
  (`input_fn` from a list) runs two prompts and `/cost`, `/mode plan`, `/exit`; EOF at the
  approval prompt counts as no (`test_prompt_eof_is_no`).
- [ ] Implement; `/compact` uses harnessy's `render_transcript` and `SUMMARY_PROMPT`.
  Commit.

### Task 8: Headless mode, `main`, packaging

**Files:**
- Create: `harness_cli/headless.py`, `harness_cli/main.py`, `harness_cli/__main__.py`,
  `harness_cli/__init__.py`
- Modify: `pyproject.toml` (name `harness-cli`, `[project.scripts] harness`, hatchling build
  of `harnessy` and `harness_cli`, `tool.uv.package = true`)
- Test: `tests/cli/test_headless.py`, `tests/cli/test_main.py`

**Interfaces:**
- Produces: `run_headless(app, prompt, output_format, out) -> int`;
  `build_parser() -> argparse.ArgumentParser`; `main(argv=None, model_factory=make_model) -> int`
  (tests inject a `ScriptedModel` factory).

- [ ] Tests: `text`, `json` and `stream-json` outputs; exit code 0 on `end_turn` and 1 on
  `max_steps`; prompt from stdin when `-p` has no argument; `--permission-mode plan` blocks
  `write_file`; bad settings JSON exits 2 with the file name; no ANSI codes when the output is
  not a terminal (`test_no_color_when_not_tty`); `-c` continues the latest session.
- [ ] Implement; `uv sync`; check `uv run harness --help` works. Commit.

### Task 9: Documentation

**Files:**
- Create: `docs/cli/usage.md` (install, flags, slash commands, settings, permissions,
  sandbox, sessions, recipes)
- Modify: `README.md` (what harness-cli is, quick start, links to `docs/cli/`)

- [ ] Write, check every flag in `usage.md` against `harness --help`, commit.

---

## Roadmap after v0.1

| Phase | Adds | Builds on |
| --- | --- | --- |
| 0.2 | Skills (`.harness/skills/*/SKILL.md`, loaded on demand, harnessy `docs/skills.md`); hooks from settings (shell commands at `before_tool`/`after_tool`) | `tools.py`, `hooks.py` |
| 0.3 | Git checkpoints and `/undo` (a commit per turn on a shadow ref); `/diff` | `session.py` |
| 0.4 | Full-screen TUI (approach B) as a second consumer of engine events | `engine.py` |
| 0.5 | Agent server over JSON-RPC (approach C); the `stream-json` events become the wire format | `engine.py`, `headless.py` |
| later | Linux Landlock/bubblewrap sandbox; images; prompt caching control; eval suite for the CLI agent | `sandbox.py`, harnessy evals |
