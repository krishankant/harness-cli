# Using harness

`harness` is a coding agent for your terminal, in the style of Claude Code and Codex. It runs
on the harnessy library in this repo: the loop, tools, hooks, approvals, streaming, context
management and sandbox you built in the course.

- [Setup](#setup)
- [Models](#models)
- [Interactive mode](#interactive-mode)
- [Headless mode (`-p`)](#headless-mode--p)
- [Flags](#flags)
- [Slash commands](#slash-commands)
- [Custom commands](#custom-commands)
- [Permissions](#permissions)
- [Sandbox](#sandbox)
- [Project instructions](#project-instructions)
- [Sessions](#sessions)
- [Settings](#settings)
- [MCP servers](#mcp-servers)
- [Recipes](#recipes)

## Setup

```bash
cd ~/claudecode/harness-cli
uv sync                      # installs dependencies and the `harness` command into .venv
uv run harness --version     # run it from this repo

uv tool install --editable .  # or: put `harness` on your PATH for every folder
```

API keys come from your environment, or from `~/.harness/.env`:

```bash
mkdir -p ~/.harness
cat > ~/.harness/.env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# OPENAI_MODEL=<a model with tool calling>
EOF
```

A project's own `.env` is never read: it belongs to the project, and an empty
`ANTHROPIC_API_KEY=` line in it would override a working login.

With `ANTHROPIC_API_KEY` set, `harness` starts on `claude-opus-5`; with `OPENAI_API_KEY` set,
`harness -m gpt-5.5` uses OpenAI. To add more models, other endpoints or prices, see
[Models](#models).

## Models

harness speaks three APIs: **Anthropic** (Messages API), **OpenAI** (Chat Completions; this
also covers every OpenAI-compatible server: OpenRouter, Groq, Together, vLLM, LM Studio, ...)
and **Ollama** (local, on `http://localhost:11434/v1`). You can use any model behind them,
switch between them in the middle of a conversation, and give each one a short name.

### Picking a model

`-m` / `--model` at startup, and `/model` in a chat, take any of:

| You write | Means |
| --- | --- |
| an alias: `opus`, `fable`, `gpt`, or one of yours | that entry in the registry |
| `provider:model`: `openai:gpt-5.5`, `ollama:qwen3-coder`, `anthropic:claude-opus-5` | that model through that provider, no config needed |
| a model id: `claude-fable-5-1`, `gpt-5.5`, `o4-mini` | provider guessed from the name (`claude-*` → Anthropic; `gpt-*`, `o1`…`o9*`, `codex-*` → OpenAI; anything else → `--provider`, default Anthropic) |

With no `-m`, harness uses `model` / `defaultModel` from settings, else `ANTHROPIC_MODEL`
(or `OPENAI_MODEL` / `OLLAMA_MODEL` when `provider` is `openai` / `ollama`), else
`claude-opus-5`.

```bash
harness -m gpt-5.5                     # OpenAI
harness -m opus                        # Anthropic, by alias
harness -m ollama:qwen3-coder          # local
harness --list-models                  # everything you can pick, with prices and key status
```

In a chat, `/model gpt` switches to OpenAI and keeps the conversation (tool calls included);
`/model opus` switches back. `/models` shows the list; `/model` alone shows the current model,
its endpoint and whether its key is set. If a switch fails (unknown name, missing key), you
stay on the current model.

### Adding models

Add entries under `models` in `~/.harness/settings.json` (all projects) or
`.harness/settings.json` (this project; its entries win on a name clash):

```json
{
  "defaultModel": "opus",
  "models": {
    "opus":     { "provider": "anthropic", "model": "claude-opus-5", "maxTokens": 32000 },
    "gpt":      { "provider": "openai", "model": "gpt-5.5" },
    "mini":     { "provider": "openai", "model": "gpt-5.5-mini", "price": { "input": 0.5, "output": 2 } },
    "groq":     { "provider": "openai", "model": "llama-4-70b",
                  "baseUrl": "https://api.groq.com/openai/v1", "apiKeyEnv": "GROQ_API_KEY",
                  "price": [0.6, 0.8] },
    "router":   { "provider": "openai", "model": "anthropic/claude-opus-5",
                  "baseUrl": "https://openrouter.ai/api/v1", "apiKeyEnv": "OPENROUTER_API_KEY" },
    "local":    { "provider": "ollama", "model": "qwen3-coder" },
    "lmstudio": { "provider": "openai", "model": "qwen3-coder-30b",
                  "baseUrl": "http://localhost:1234/v1", "apiKeyEnv": "LMSTUDIO_KEY" }
  }
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `model` | yes | the id the API expects |
| `provider` | no | `anthropic`, `openai` or `ollama`; guessed from `model` when left out |
| `baseUrl` | no | another endpoint for that API (proxies, gateways, OpenAI-compatible servers) |
| `apiKeyEnv` | no | the environment variable with the key (default `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`; Ollama needs none). Put the key itself in your environment or `~/.harness/.env`, never in settings |
| `price` | no | USD per million tokens, `{"input": x, "output": y}` or `[x, y]`; makes `/cost` and `--max-cost` work. Built-in prices (`harnessy/cost.py`) cover `claude-opus-5`, `claude-fable-5-1` and `gpt-5.5`, including dated ids |
| `maxTokens` | no | output-token limit per reply (Anthropic; default 16000) |

The model must support tool calling, or it can only chat. A bad entry stops harness with its
name and the problem (exit code 2).

## Interactive mode

```bash
harness                         # chat in the current folder
harness "why is the build slow?" # chat, starting with a prompt
harness -C ~/code/app           # chat in another folder
```

```
harness 0.1.0  ·  /help for commands  ·  Ctrl-D to quit
  /Users/you/code/app
  model claude-opus-5 · mode default · sandbox workspace-write (Seatbelt: no network, writes only inside the workspace)

› Create notes.txt containing the single word hello.
? Allow write_file → notes.txt
    + hello
  [y]es  [n]o  [a]lways for this session › y
● write_file(notes.txt)
  ⎿ Wrote 6 characters to notes.txt
Done — `notes.txt` contains `hello`.
```

| You type | What happens |
| --- | --- |
| text | a prompt to the agent; its answer streams in as it is written |
| `/command args` | a [slash command](#slash-commands) or a [custom command](#custom-commands) |
| `!git status` | runs the command yourself, through the same sandbox; nothing goes to the model |
| `@src/app.py` in a prompt | attaches that workspace file's contents to the prompt |
| a line ending in `\` | keep typing on the next line |
| Ctrl-C during a turn | stops the agent at its next model or tool call (a running tool finishes first); Ctrl-C again abandons the turn |
| Ctrl-C at the prompt | clears the line |
| Ctrl-D, `/exit` | quit |

Each tool call shows as one line, `● tool(main argument)`, followed by the first line of its
result, `⎿ ...`, in red if it failed. While a tool runs, or while the model is thinking before
its first word, an animated line shows what's happening and for how long:

```
● run_shell(uv run pytest -q)
  ⠹ Running… 12s · Ctrl-C to interrupt
```

It appears only after 0.3 s, so quick tools don't flicker, and it is erased as soon as the
result, text or an approval prompt arrives. It is shown only on a terminal: headless `-p`
output, pipes and files never contain it. Approval prompts show the command, or the lines a file
edit removes (`-`) and adds (`+`).

## Headless mode (`-p`)

One turn, no questions, then exit: for scripts, CI and pipes. Like `claude -p` or `codex exec`.

```bash
harness -p "summarize README.md"
git diff | harness -p "review this diff for bugs"          # stdin is appended in <stdin> tags
cat error.log | harness -p                                 # stdin alone is the prompt
harness -p "list the TODOs" --output-format json | jq .result
harness -p "fix the failing test" --allowed-tools "edit_file,run_shell(uv run pytest*)"
```

Nobody can answer a prompt, so anything that would ask is declined, and the model is told how
you could allow it. Allow what the task needs with `--allowed-tools`, `--permission-mode`, or
rules in settings.

| `--output-format` | Output on stdout |
| --- | --- |
| `text` (default) | the final answer |
| `json` | `{"result", "stop_reason", "error", "session_id", "steps", "usage", "cost_usd"}` |
| `stream-json` | one JSON object per line: `text`, `tool_start`, `tool_end`, then `done` (same fields as `json`) |

Exit code `0` means the run ended normally (`end_turn`); `1` means it stopped for another reason
(`max_steps`, `max_cost`, `model_error`, `blocked`, ...), named on stderr; `2` means bad flags,
settings or session id. Failed tool calls are also echoed to stderr.

## Flags

| Flag | Meaning |
| --- | --- |
| `prompt` | the first prompt (interactive) or the task (`-p`) |
| `-p`, `--print` | headless: one turn, print, exit |
| `--output-format text\|json\|stream-json` | output of `-p` |
| `-c`, `--continue` | continue the most recent conversation in this folder |
| `-r ID`, `--resume ID` | resume a conversation (the whole id, its start, or its last 4 characters); `-r` alone lists them |
| `-C DIR`, `--cd DIR` | workspace folder (default: current folder) |
| `-m NAME`, `--model NAME` | an alias, `provider:model`, or a model id; see [Models](#models) |
| `--provider anthropic\|openai\|ollama` | provider for a bare model id that doesn't name one, and for the default model |
| `--list-models` | list the models you can pick, then exit |
| `--permission-mode default\|accept-edits\|plan\|bypass` | see [Permissions](#permissions) |
| `--dangerously-skip-permissions` | same as `--permission-mode bypass` |
| `--allowed-tools RULES` | comma-separated rules that run without asking; repeatable |
| `--disallowed-tools RULES` | comma-separated rules that are always refused; repeatable |
| `--sandbox workspace-write\|off` | see [Sandbox](#sandbox) |
| `--max-steps N` | model calls per turn (default 50) |
| `--max-cost USD` | stop once the conversation has cost this much (needs a priced model, see `harnessy/cost.py`) |
| `--system-prompt TEXT` | replace the built-in system prompt |
| `--append-system-prompt TEXT` | add to the end of the system prompt |
| `--no-color` | no ANSI colours (also `NO_COLOR=1`; colour is off anyway when output isn't a terminal) |
| `--version` | print the version |

## Slash commands

| Command | Does |
| --- | --- |
| `/help` | list commands, including custom ones |
| `/status` | workspace, model, permission mode, sandbox, session id, instruction files, MCP errors |
| `/clear` | start a new conversation (the old one stays saved) |
| `/compact [focus]` | replace the conversation with a model-written summary, to free context |
| `/cost` | tokens and dollars so far in this conversation |
| `/model [name]` | show or switch the model, any provider; the conversation carries over |
| `/models` | the models you can switch to, with provider, price and key status |
| `/mode [mode]` | show or switch the permission mode |
| `/tools` | every tool and whether it runs, asks or is denied right now |
| `/todo` | the agent's todo list |
| `/sessions` | saved conversations for this folder |
| `/resume <id>` | switch to a saved conversation |
| `/init` | have the agent write a `HARNESS.md` for this project |
| `/exit` | quit |

## Custom commands

A Markdown file in `.harness/commands/` (this project) or `~/.harness/commands/` (everywhere)
becomes a slash command named after the file. A project command wins over a user command of
the same name.

```markdown
description: Review a file for bugs
Review $ARGUMENTS for correctness bugs. List each with path:line and a one-line fix.
```

`/review src/parser.py` sends that text with `$ARGUMENTS` replaced. Without `$ARGUMENTS`,
whatever you type after the command is added on a new paragraph. The optional
`description:` line is what `/help` shows.

## Permissions

Each tool is one of four kinds, and the permission mode decides per kind:

| Kind | Tools |
| --- | --- |
| read | `read_file`, `list_files`, `search_files`, `todo` |
| edit | `write_file`, `edit_file` |
| execute | `run_shell`, every MCP tool |
| agent | `spawn_subagent` |

| Mode | read | edit | execute | agent | Like |
| --- | --- | --- | --- | --- | --- |
| `default` | run | ask | ask | run | Claude Code default; Codex auto |
| `accept-edits` | run | run | ask | run | Claude Code acceptEdits |
| `plan` | run | refuse | refuse | refuse | Claude Code plan mode; Codex read-only |
| `bypass` | run | run | run | run | `--dangerously-skip-permissions`; Codex full access |

A subagent runs under the same permission hook as you, so it asks for the same things you would
be asked for. Switch modes during a chat with `/mode`.

**Rules** fine-tune the `ask` cases. A rule is `tool` or `tool(pattern)`; the pattern is a glob
matched against the call's main argument: the command for `run_shell`, the path for file tools.

```json
{
  "permissions": {
    "defaultMode": "default",
    "allow": ["run_shell(git status*)", "run_shell(git diff*)", "run_shell(uv run pytest*)", "edit_file(src/*)"],
    "deny": ["run_shell(git push*)", "run_shell(rm -rf*)", "read_file(.env*)", "write_file(.env*)"]
  }
}
```

Order of checks for every call: the mode refuses it → refused. A deny rule matches → refused
(even for read tools). The mode allows it, you answered "always" earlier, or an allow rule
matches → it runs. Otherwise you're asked (or, in `-p` mode, it's declined).

### Why bypass still "asks" inside

harnessy's lethal-trifecta check (week 7) refuses to build an agent whose tools can read
private data, take in untrusted input, and send data out, unless every way out needs approval.
`run_shell` has all three. In bypass mode `run_shell` therefore keeps the decision `ask`, and
the permission hook answers yes itself. The check still holds, and turning approvals off is a
visible choice in code (`harness_cli/permissions.py`) rather than a hole in the check.

## Sandbox

Every `run_shell` call (and every `!command`) runs through harnessy's `run_command`: only
`PATH`, `LANG`, `LC_ALL` and `TERM` are passed through (your API keys never reach the
command), `HOME` is the workspace, the time limit really kills the process group, and output
is capped.

With `--sandbox workspace-write` (the default) on macOS, the command also runs inside a Seatbelt
profile:

- no network access;
- writes only inside the workspace and the temp folders;
- no reads of `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/gh`, `~/.netrc` or `~/.harness`.

So `pip install`, `git push` or `curl` fail inside the agent's shell. Run them yourself, or
start with `--sandbox off` when the task needs the network. On Linux and other systems, only
the first layer applies (`/status` says so). `docs/sandbox.md` explains both layers and what
they don't stop.

## Project instructions

Before each conversation the system prompt gets, in this order:

1. the built-in prompt (or `--system-prompt` / `systemPrompt`);
2. the workspace path, git status, platform, date and tool list;
3. `~/.harness/HARNESS.md` (your personal instructions);
4. `HARNESS.md`, `AGENTS.md` and `CLAUDE.md` from the workspace root, whichever exist;
5. `--append-system-prompt` / `appendSystemPrompt`.

`/init` asks the agent to write a `HARNESS.md` for the project.

## Sessions

Every conversation is saved after each turn to
`~/.harness/sessions/<folder-key>/<id>.jsonl`: a header line, one line per message, and a usage
line. Ids look like `20261003-142501-a1b2`.

```bash
harness -c                 # continue the latest conversation in this folder
harness -r                 # list conversations for this folder
harness -r a1b2            # resume by the last 4 characters (or the start, or the whole id)
harness -p -c "and now?"   # continue headlessly
```

In a chat: `/sessions`, `/resume <id>`, `/clear` (new conversation). The file is replaced
atomically on each save; if one is damaged anyway, unreadable lines are skipped on load.

## Settings

`~/.harness/settings.json` (yours) and `<workspace>/.harness/settings.json` (the project's)
are merged: the project's values win, flags win over both, and the `allow`/`deny` lists are
combined rather than replaced. `HARNESS_HOME` moves `~/.harness`.

```json
{
  "provider": "anthropic",
  "defaultModel": "opus",
  "models": { "opus": { "model": "claude-opus-5" } },
  "permissions": { "defaultMode": "default", "allow": [], "deny": [] },
  "sandbox": "workspace-write",
  "maxSteps": 50,
  "maxCostUsd": 2.0,
  "shellTimeout": 120,
  "contextBudgetTokens": 120000,
  "systemPrompt": null,
  "appendSystemPrompt": "Prefer small commits.",
  "mcpServers": {}
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `provider` | `anthropic` | provider for bare model ids and for the default model |
| `defaultModel` (or `model`) | see [Models](#models) | the model to start with |
| `models` | built-ins | the model registry; user and project entries are merged by name |
| `permissions.defaultMode` | `default` | starting permission mode |
| `permissions.allow` / `deny` | `[]` | rules, see [Permissions](#permissions) |
| `sandbox` | `workspace-write` | or `off` |
| `maxSteps` | 50 | model calls per turn |
| `maxCostUsd` | none | budget for the conversation |
| `shellTimeout` | 120 | seconds per `run_shell` call |
| `contextBudgetTokens` | 120000 | above this, the oldest turns are dropped from what the model sees (week 4); the saved conversation keeps everything |
| `systemPrompt` | built-in | replaces the base prompt |
| `appendSystemPrompt` | none | added at the end |
| `mcpServers` | `{}` | see below |

Bad JSON or an unknown value stops `harness` with the file name and exit code 2.

## MCP servers

Tools from any MCP server that speaks stdio (harnessy week 9):

```json
{
  "mcpServers": {
    "notes": { "command": ["uv", "run", "python", "-m", "scripts.mcp_notes_server"], "cwd": "/path/to/harness-cli" },
    "fs": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."] }
  }
}
```

A server's tools are named `<server>__<tool>` and count as execute tools: they ask in default
mode and are refused in plan mode. A server that fails to start is reported in the banner and
in `/status`, and the session goes on without it.

## Recipes

```bash
# A read-only code tour
harness --permission-mode plan "walk me through how a request flows through this app"

# Let tests and git inspection run freely, ask for everything else
harness --allowed-tools "run_shell(uv run pytest*),run_shell(git status*),run_shell(git diff*)"

# CI: fix lint errors and fail the job if the agent didn't finish
harness -p "run ruff check . and fix every error" \
  --permission-mode accept-edits --allowed-tools "run_shell(ruff *)" --max-cost 1

# Local and free
harness -m ollama:qwen3-coder

# Plan with one model, implement with another
harness -m fable "plan the refactor of src/db; don't edit yet"   # then in the chat: /model gpt
```
