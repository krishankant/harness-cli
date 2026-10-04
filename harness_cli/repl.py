"""The interactive loop: read a line, run a command or a turn, repeat."""

from __future__ import annotations

from typing import Callable

from harness_cli import __version__
from harness_cli.app import App
from harness_cli.commands import COMMANDS, EXIT, expand_mentions, load_custom_commands, parse_input, run_shell_escape
from harness_cli.config import harness_home
from harness_cli.sandbox import describe

PROMPT = "› "
CONTINUATION = "… "


def _setup_readline() -> Callable[[], None]:
    """Line editing and a history file, where readline exists. Returns a function that saves."""
    try:
        import readline
    except ImportError:  # Windows without pyreadline
        return lambda: None
    path = harness_home() / "history"
    try:
        readline.read_history_file(path)
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(1000)

    def save() -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(path)
        except OSError:
            pass

    return save


def read_prompt(input_fn: Callable[[str], str], prompt: str) -> str:
    """One logical line; a trailing backslash continues it on the next physical line."""
    lines = []
    text = input_fn(prompt)
    while text.endswith("\\"):
        lines.append(text[:-1])
        text = input_fn(CONTINUATION)
    lines.append(text)
    return "\n".join(lines)


def banner(app: App) -> None:
    r = app.renderer
    r.note(r.style(f"harness {__version__}", "bold", "magenta") + r.style("  ·  /help for commands  ·  Ctrl-D to quit", "dim"))
    r.info(f"  {app.workspace}")
    r.info(f"  model {app.model.name} · mode {app.permissions.mode} · sandbox {describe(app.settings.sandbox)}")
    if app.session.messages:
        r.info(f"  resumed {app.session.id}: {app.session.title}")
    for err in app.mcp_errors:
        r.warn(f"  {err}")
    r.note("")


def handle_line(app: App, line: str) -> str | None:
    """Run one line of input. Returns EXIT to quit."""
    kind, name, rest = parse_input(line)
    if kind == "empty":
        return None
    if kind == "shell":
        run_shell_escape(app, rest)
        return None
    if kind == "slash":
        if name in COMMANDS:
            return COMMANDS[name][1](app, rest)
        custom = load_custom_commands(app.workspace).get(name)
        if custom is None:
            app.renderer.error(f"Unknown command /{name}. Type /help for the list.")
            return None
        prompt = custom.render(rest)
    else:
        prompt = rest
    prompt, attached = expand_mentions(prompt, app.workspace)
    if attached:
        app.renderer.info(f"attached {', '.join(attached)}")
    app.run_turn(prompt)
    app.renderer.note("")
    return None


def run_repl(app: App, input_fn: Callable[[str], str] | None = None, first_prompt: str | None = None) -> int:
    save_history = _setup_readline() if input_fn is None else (lambda: None)
    input_fn = input_fn or input
    banner(app)
    try:
        if first_prompt:
            if handle_line(app, first_prompt) == EXIT:
                return 0
        while True:
            try:
                line = read_prompt(input_fn, app.renderer.style(PROMPT, "bold", "magenta"))
            except EOFError:
                app.renderer.line()
                return 0
            except KeyboardInterrupt:
                app.renderer.line()
                continue
            try:
                if handle_line(app, line) == EXIT:
                    return 0
            except KeyboardInterrupt:
                app.renderer.warn("\nTurn abandoned.")
    finally:
        save_history()
        app.close()
