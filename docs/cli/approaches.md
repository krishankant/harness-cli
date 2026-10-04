# Approaches: how to turn harnessy into a command-line agent

harnessy is a library. You build an `Agent`, call `agent.run(task)`, and get back a
`RunResult`. Claude Code and Codex are programs: you type `claude` or `codex` in a
terminal, talk to the agent over many turns, approve what it wants to do, and come
back to the conversation tomorrow. This page compares three ways to close that gap
and says which one harness-cli takes.

## What the CLI has to do

Every approach has to deliver the same features. These are the ones Claude Code and
Codex users rely on every day:

| Feature | Claude Code | Codex | What it needs from the harness |
| --- | --- | --- | --- |
| Interactive chat in the terminal | `claude` | `codex` | A conversation that lasts many turns, not one task |
| One-shot, scriptable mode | `claude -p "..."` | `codex exec "..."` | A run with no human; permissions fixed in advance |
| Live output | streaming text and tool lines | same | Streaming events (harnessy week 7) |
| Approve risky actions | permission prompts, modes | approval policy | `ApprovalHook` (week 6), driven from the terminal |
| Permission modes | default, acceptEdits, plan, bypass | read-only, auto, full-access | Different policy tables for the same tools |
| Slash commands | `/help`, `/clear`, `/cost`, custom `.md` commands | `/model`, `/status`, ... | A command layer in front of the agent |
| Project instructions | `CLAUDE.md` | `AGENTS.md` | Files read into the system prompt |
| Resume a conversation | `--continue`, `--resume` | `codex resume` | Sessions saved to disk and loaded back |
| Sandboxing | permission rules, optional sandbox | Seatbelt / Landlock sandbox | The week 7 sandbox, plus an OS sandbox |
| MCP servers | `.mcp.json` | `config.toml` | The week 9 MCP client |

## Approach A: a thin CLI on top of the harnessy library (chosen)

Keep `harnessy/` as the engine and add a second package, `harness_cli/`, that only
does what a program does and a library doesn't: parse flags, read settings, draw the
terminal, ask the human, save sessions. Every agent behaviour still comes from the
pieces you built in the course: the loop, the tool registry, hooks, approvals,
streaming, context management, the sandbox, MCP.

The library needs one small change: `Agent.run` takes an optional `history`, so a
conversation can continue from earlier turns instead of starting fresh. Everything
else plugs in through the existing extension points (hooks, tools, the approver
callback).

- **For:** smallest amount of new code; every lesson stays true; easy to test with
  `ScriptedModel` and no network; no new dependencies (standard library only).
- **Against:** the UI is a line-based terminal, not a full-screen app. A long run blocks
  the prompt until it ends or you press Ctrl-C.

## Approach B: a full-screen terminal app (TUI)

Build the UI with a TUI framework (Textual or prompt_toolkit in Python; Claude Code
uses Ink, a React renderer for terminals). You get panes, a status bar, scrollback you
can search, and type-ahead while the agent works.

- **For:** looks and feels closest to Claude Code; better for long sessions.
- **Against:** a large new dependency and a lot of UI code that has nothing to do with
  harness engineering; much harder to test; harder to use in pipes and scripts, so you
  still need approach A's headless mode.

## Approach C: an agent server plus thin clients

Run the agent as a long-lived process that speaks JSON-RPC over stdio or a socket, and
make the CLI one client of it. This is the shape of Codex's app server and of Claude
Code's SDK mode: the same core drives the terminal, an IDE extension and a web UI.

- **For:** one engine, many front ends; sessions survive a closed terminal; the IDE can
  show diffs while the terminal shows chat.
- **Against:** a protocol to design and version, process management, and two programs to
  debug before anything works. Worth it once there is a second client, not before.

## Decision

**Approach A now, built so B and C can follow.** The engine (`harness_cli/engine.py`)
talks to the outside world only through events (`TextDelta`, `ToolStart`, `ToolEnd`,
`ApprovalRequest`, `Done`). The line-based REPL is one consumer of those events and
headless mode is another, which writes them as JSON lines. A TUI (B) would be a third
consumer, and the `stream-json` output is already most of the wire format a server (C)
would need.

## Design choices inside approach A

| Question | Choice | Why |
| --- | --- | --- |
| Where the copy lives | `~/claudecode/harness-cli`, a new git repo | The course repo keeps its stubs and week branches; the CLI can change the library freely |
| Dependencies | none beyond harnessy's | `argparse`, `readline`, ANSI colours and `json` are enough for a line-based UI |
| Permission prompts | asked on the main thread through the event queue | The agent runs in a worker thread; a prompt printed from it would interleave with streamed text |
| Ctrl-C | a cancel hook that blocks the next model or tool call | Python can't kill a thread; the loop already ends cleanly on a `Block` |
| Sessions | one JSON-lines file per conversation under `~/.harness/sessions/` | Append-friendly, readable, survives crashes mid-session |
| Shell isolation | harnessy's `run_command` plus macOS Seatbelt when available | Same layering as `docs/sandbox.md`: hygiene first, OS isolation on top |
| Trifecta check | kept on; bypass mode uses an explicit always-yes approver | The check stays meaningful: turning approvals off is a visible, named choice |
| Settings format | JSON, user file merged with project file | Same shape as Claude Code's `settings.json`; no TOML/YAML parser needed |
