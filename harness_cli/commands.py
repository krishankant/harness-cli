"""What you can type besides a prompt: /slash commands (built-in and custom), !shell, @file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from harness_cli import session as sessions
from harness_cli.config import MODES, harness_home
from harness_cli.instructions import instruction_sources
from harness_cli.sandbox import describe, run_sandboxed
from harnessy.context import SUMMARY_PROMPT, render_transcript
from harnessy.cost import PRICES, price_for
from harnessy.tools.files import resolve_inside
from harnessy.types import Message

if TYPE_CHECKING:
    from harness_cli.app import App

MAX_MENTION_CHARS = 100_000
_MENTION = re.compile(r"(?<!\S)@([\w./~-]+)")

INIT_PROMPT = """Look through this project (list files, read the README, build files and a few key \
modules) and write a HARNESS.md at the workspace root for future coding sessions. Include: what the \
project is, how to install, build, test and lint it (exact commands), the layout of the main folders, \
and conventions a contributor must follow. Keep it under 80 lines. If HARNESS.md exists, improve it."""


# --- parsing ---------------------------------------------------------------------------


def parse_input(line: str) -> tuple[str, str, str]:
    """("empty"|"slash"|"shell"|"prompt", name, rest)."""
    text = line.strip()
    if not text:
        return "empty", "", ""
    if text.startswith("/") and len(text) > 1 and not text.startswith("//"):
        name, _, rest = text[1:].partition(" ")
        return "slash", name.lower(), rest.strip()
    if text.startswith("!"):
        return "shell", "", text[1:].strip()
    return "prompt", "", text


def expand_mentions(text: str, workspace: Path) -> tuple[str, list[str]]:
    """Attach the contents of every @path that names a file in the workspace. Returns the new
    prompt and the paths attached; an @word that isn't a file is left as it is."""
    attached: list[str] = []
    blocks: list[str] = []
    for rel in dict.fromkeys(_MENTION.findall(text)):
        try:
            path = resolve_inside(workspace, rel.rstrip(".,;:"))
        except ValueError:
            continue
        if not path.is_file():
            continue
        body = path.read_text(errors="replace")
        if len(body) > MAX_MENTION_CHARS:
            body = body[:MAX_MENTION_CHARS] + "\n[truncated]"
        name = rel.rstrip(".,;:")
        attached.append(name)
        blocks.append(f'<file path="{name}">\n{body}\n</file>')
    if not blocks:
        return text, []
    return text + "\n\nAttached files:\n" + "\n".join(blocks), attached


# --- custom commands -------------------------------------------------------------------


@dataclass(frozen=True)
class CustomCommand:
    name: str
    body: str
    description: str
    source: Path

    def render(self, args: str) -> str:
        if "$ARGUMENTS" in self.body:
            return self.body.replace("$ARGUMENTS", args)
        return f"{self.body}\n\n{args}".strip() if args else self.body


def _read_command(path: Path) -> CustomCommand:
    text = path.read_text(errors="replace").strip()
    first, _, rest = text.partition("\n")
    if first.lower().startswith("description:"):
        return CustomCommand(path.stem.lower(), rest.strip(), first.split(":", 1)[1].strip(), path)
    return CustomCommand(path.stem.lower(), text, first[:60], path)


def load_custom_commands(workspace: Path) -> dict[str, CustomCommand]:
    """User commands from ~/.harness/commands, then project commands (which win on a clash)."""
    found: dict[str, CustomCommand] = {}
    for folder in (harness_home() / "commands", Path(workspace) / ".harness" / "commands"):
        if folder.is_dir():
            for path in sorted(folder.glob("*.md")):
                cmd = _read_command(path)
                found[cmd.name] = cmd
    return found


# --- built-in commands -----------------------------------------------------------------

EXIT = "exit"
Handler = Callable[["App", str], "str | None"]
COMMANDS: dict[str, tuple[str, Handler]] = {}


def command(name: str, help_text: str):
    def register(fn: Handler) -> Handler:
        COMMANDS[name] = (help_text, fn)
        return fn

    return register


@command("help", "Show this help")
def _help(app: App, args: str) -> None:
    r = app.renderer
    r.note(r.style("Commands", "bold"))
    for name, (text, _) in COMMANDS.items():
        r.note(f"  /{name:<10} {text}")
    custom = load_custom_commands(app.workspace)
    if custom:
        r.note(r.style("Custom commands", "bold"))
        for cmd in custom.values():
            r.note(f"  /{cmd.name:<10} {cmd.description}")
    r.note(r.style("Input", "bold"))
    r.note("  !command    run a shell command yourself (sandboxed, not sent to the model)")
    r.note("  @path       attach a workspace file to your prompt")
    r.note("  line\\       end a line with \\ to keep typing on the next one")
    r.note("  Ctrl-C      interrupt the agent · Ctrl-D quit")


@command("exit", "Quit (Ctrl-D also works)")
def _exit(app: App, args: str) -> str:
    return EXIT


@command("clear", "Start a new conversation")
def _clear(app: App, args: str) -> None:
    app.new_session()
    app.renderer.info(f"New conversation {app.session.id}.")


@command("status", "Workspace, model, mode, sandbox and session")
def _status(app: App, args: str) -> None:
    r, s = app.renderer, app.settings
    files = ", ".join(str(p) for p in instruction_sources(app.workspace)) or "none"
    for label, value in [
        ("workspace", app.workspace),
        ("model", f"{app.model.name} ({s.provider})"),
        ("mode", app.permissions.mode),
        ("sandbox", describe(s.sandbox)),
        ("session", app.session.id),
        ("instructions", files),
    ]:
        r.note(f"  {label:<13} {value}")
    for err in app.mcp_errors:
        r.warn(f"  {err}")


@command("cost", "Tokens and cost of this conversation")
def _cost(app: App, args: str) -> None:
    u = app.engine.usage
    price = price_for(app.model.name, PRICES)
    money = f"${app.engine.cost_usd:.4f}" if price else "unknown (no price for this model in harnessy/cost.py)"
    app.renderer.note(f"  tokens in {u.input_tokens:,} · out {u.output_tokens:,} · cost {money}")
    if app.settings.max_cost_usd is not None:
        app.renderer.note(f"  budget ${app.settings.max_cost_usd:.2f}")


@command("model", "Show or switch the model: /model <name>")
def _model(app: App, args: str) -> None:
    if not args:
        app.renderer.note(f"  {app.model.name} ({app.settings.provider})")
        return
    try:
        app.set_model(args)
    except Exception as e:
        app.renderer.error(f"Could not switch model: {e}")
        return
    app.renderer.info(f"Model is now {app.model.name}.")


@command("mode", f"Show or switch the permission mode: {', '.join(MODES)}")
def _mode(app: App, args: str) -> None:
    if not args:
        app.renderer.note(f"  {app.permissions.mode}  (modes: {', '.join(MODES)})")
        return
    if args not in MODES:
        app.renderer.error(f"Unknown mode '{args}'. Use one of: {', '.join(MODES)}.")
        return
    app.permissions.set_mode(args)
    app.renderer.info(f"Permission mode is now {args}.")


@command("tools", "List the tools and whether each runs, asks or is denied")
def _tools(app: App, args: str) -> None:
    for t in app.tools:
        decision = app.permissions.effective(t.name)
        app.renderer.note(f"  {t.name:<22} {decision:<22} {t.spec.description.split('.')[0][:60]}")


@command("todo", "Show the agent's todo list")
def _todo(app: App, args: str) -> None:
    app.renderer.note(app.todo.render())


@command("sessions", "List saved conversations for this folder")
def _sessions(app: App, args: str) -> None:
    infos = sessions.list_sessions(app.workspace)
    if not infos:
        app.renderer.info("No saved conversations for this folder yet.")
    for i in infos:
        mark = "*" if i.id == app.session.id else " "
        app.renderer.note(f" {mark}{i.id}  {i.modified:%Y-%m-%d %H:%M}  {i.turns:>3} turns  {i.title}")


@command("resume", "Switch to a saved conversation: /resume <id>")
def _resume(app: App, args: str) -> None:
    if not args:
        _sessions(app, "")
        return
    try:
        app.switch_session(sessions.load(app.workspace, args))
    except sessions.SessionError as e:
        app.renderer.error(str(e))
        return
    app.renderer.info(f"Resumed {app.session.id}: {app.session.title}")


@command("compact", "Summarize the conversation to free context: /compact [focus]")
def _compact(app: App, args: str) -> None:
    if len(app.session.messages) < 2:
        app.renderer.info("Nothing to compact yet.")
        return
    focus = f"\n\nPay special attention to: {args}" if args else ""
    text = "Transcript:\n" + render_transcript(app.session.messages) + focus
    try:
        response = app.model.complete([Message("user", text=text)], [], system=SUMMARY_PROMPT)
    except Exception as e:
        app.renderer.error(f"Compaction failed: {type(e).__name__}: {e}")
        return
    if response.stop_reason != "end_turn" or not response.message.text.strip():
        app.renderer.error(f"Compaction failed: the model stopped with '{response.stop_reason}'. Nothing changed.")
        return
    before = len(app.session.messages)
    app.session.messages = [
        Message("user", text="[Summary of our conversation so far]\n" + response.message.text.strip()),
        Message("assistant", text="Understood. I'll continue from that summary."),
    ]
    app.engine.usage = app.engine.usage + response.usage
    app.engine.reset_context()
    app.session.save()
    app.renderer.info(f"Compacted {before} messages into a summary.")


@command("init", "Have the agent write a HARNESS.md for this project")
def _init(app: App, args: str) -> None:
    app.run_turn(INIT_PROMPT)


def run_shell_escape(app: App, command_line: str) -> None:
    """!command: run it yourself, through the same sandbox; nothing goes to the model."""
    if not command_line:
        return
    result = run_sandboxed(command_line, app.workspace, app.settings.shell_timeout_s, app.settings.sandbox)
    if result.output.strip():
        app.renderer.note(result.output.rstrip())
    status = "timed out" if result.timed_out else f"exit code {result.exit_code}"
    app.renderer.info(f"[{status}]")
