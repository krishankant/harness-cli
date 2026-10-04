"""The `harness` command: parse flags, load settings, then run the REPL or one headless turn."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from harness_cli import __version__
from harness_cli import session as sessions
from harness_cli.app import App, ModelFactory
from harness_cli.commands import model_table
from harness_cli.config import MODES, PROVIDERS, SANDBOXES, ConfigError, harness_home, load_settings
from harness_cli.headless import FORMATS, run_headless
from harness_cli.permissions import Rule
from harness_cli.models import ModelError, Registry, build_model
from harness_cli.render import Renderer
from harness_cli.repl import run_repl
from harnessy.safety import TrifectaError

EPILOG = """examples:
  harness                                   chat in the current folder
  harness "explain this repo"               chat, starting with a prompt
  harness -p "summarize README.md"          one answer, then exit
  git diff | harness -p "review this diff"  prompt from stdin
  harness -c                                continue the last conversation here
  harness --permission-mode plan            read-only: no edits, no shell
  harness -m gpt-5.5                        use an OpenAI model (or: -m opus, -m ollama:qwen3-coder)
  harness --list-models                     the models you can use and whether their keys are set
  harness --allowed-tools "run_shell(uv run pytest*)" -p "fix the tests"

settings: ~/.harness/settings.json and .harness/settings.json; docs/cli/usage.md has them all."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="harness",
        description="A coding agent in your terminal, built on the harnessy harness.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("prompt", nargs="?", help="first prompt (interactive) or the task (with -p)")
    p.add_argument("-p", "--print", action="store_true", help="run one turn without asking anything, print the result, exit")
    p.add_argument("--output-format", choices=FORMATS, default="text", help="with -p: text (default), json, or stream-json")
    p.add_argument("-c", "--continue", dest="cont", action="store_true", help="continue the most recent conversation in this folder")
    p.add_argument("-r", "--resume", nargs="?", const="", metavar="ID", help="resume a conversation by id (no id: list them)")
    p.add_argument("-C", "--cd", metavar="DIR", help="workspace folder (default: the current folder)")
    p.add_argument("-m", "--model", help="alias from settings, provider:model, or a model id (e.g. opus, gpt-5.5, ollama:qwen3-coder)")
    p.add_argument("--provider", choices=PROVIDERS, help="provider for a bare model id that doesn't name one (default: anthropic)")
    p.add_argument("--list-models", action="store_true", help="list the configured models and exit")
    p.add_argument("--permission-mode", choices=MODES, help="default, accept-edits, plan (read-only), or bypass")
    p.add_argument("--dangerously-skip-permissions", action="store_true", help="same as --permission-mode bypass: never ask")
    p.add_argument("--allowed-tools", action="append", metavar="RULES", help='comma-separated rules that skip the prompt, e.g. "run_shell(git *),edit_file"; repeatable')
    p.add_argument("--disallowed-tools", action="append", metavar="RULES", help='comma-separated rules that always refuse, e.g. "run_shell(rm *)"; repeatable')
    p.add_argument("--sandbox", choices=SANDBOXES, help="workspace-write (default; Seatbelt on macOS) or off")
    p.add_argument("--max-steps", type=int, help="model calls per turn (default 50)")
    p.add_argument("--max-cost", type=float, metavar="USD", help="stop when the conversation has cost this much")
    p.add_argument("--system-prompt", help="replace the built-in system prompt")
    p.add_argument("--append-system-prompt", help="add text to the end of the system prompt")
    p.add_argument("--no-color", action="store_true", help="plain output (also: NO_COLOR=1)")
    p.add_argument("--version", action="version", version=f"harness {__version__}")
    return p


def _split_rules(values: list[str] | None) -> list[str] | None:
    """--allowed-tools "a, b" c -> [a, b, c]; commas inside parentheses stay."""
    if not values:
        return None
    rules: list[str] = []
    for value in values:
        depth, start = 0, 0
        for i, ch in enumerate(value):
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 0:
                rules.append(value[start:i])
                start = i + 1
        rules.append(value[start:])
    return [r.strip() for r in rules if r.strip()]


def _load_env() -> None:
    """API keys from ~/.harness/.env, if present. A project's .env is not read: it is the
    project's, and an empty ANTHROPIC_API_KEY there would override a working login."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(harness_home() / ".env", override=False)


def main(
    argv: list[str] | None = None,
    model_factory: ModelFactory = build_model,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> int:
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    args = build_parser().parse_args(argv)
    workspace = Path(args.cd or os.getcwd()).expanduser().resolve()
    if not workspace.is_dir():
        stderr.write(f"harness: no such folder: {workspace}\n")
        return 2

    def fail(message: str, code: int = 2) -> int:
        stderr.write(f"harness: {message}\n")
        return code

    _load_env()
    mode = "bypass" if args.dangerously_skip_permissions else args.permission_mode
    allow, deny = _split_rules(args.allowed_tools), _split_rules(args.disallowed_tools)
    try:
        for rule in [*(allow or []), *(deny or [])]:
            Rule.parse(rule)
        settings = load_settings(
            workspace,
            {
                "provider": args.provider,
                "model": args.model,
                "permission_mode": mode,
                "allow": allow,
                "deny": deny,
                "sandbox": args.sandbox,
                "max_steps": args.max_steps,
                "max_cost_usd": args.max_cost,
                "system_prompt": args.system_prompt,
                "append_system_prompt": args.append_system_prompt,
            },
        )
    except (ConfigError, ValueError) as e:
        return fail(str(e))

    try:
        registry = Registry.from_settings(settings)
        if args.list_models:
            stdout.write("\n".join(model_table(registry)) + "\n")
            return 0
        registry.resolve(settings.model)  # fail early on an unknown default
    except (ConfigError, ModelError) as e:
        return fail(str(e))

    # Which conversation?
    session = None
    try:
        if args.resume == "" and not args.print:
            infos = sessions.list_sessions(workspace)
            for i in infos:
                stdout.write(f"{i.id}  {i.modified:%Y-%m-%d %H:%M}  {i.turns:>3} turns  {i.title}\n")
            if not infos:
                stdout.write("No saved conversations for this folder.\n")
            return 0
        if args.resume:
            session = sessions.load(workspace, args.resume)
        elif args.cont:
            session = sessions.latest(workspace)
            if session is None and args.print:
                return fail("no conversation to continue in this folder")
    except sessions.SessionError as e:
        return fail(str(e))

    prompt = args.prompt
    if args.print and not prompt and not stdin.isatty():
        prompt = stdin.read().strip()
    if args.print and not prompt:
        return fail("-p needs a prompt (as an argument or on stdin)")
    if args.print and args.prompt and not stdin.isatty():
        piped = stdin.read().strip()
        if piped:
            prompt = f"{args.prompt}\n\n<stdin>\n{piped}\n</stdin>"

    color = False if (args.no_color or args.print) else None
    renderer = Renderer(stdout if not args.print else stderr, color=color, input_fn=input_fn or input)
    try:
        app = App(workspace, settings, renderer, model_factory, interactive=not args.print, session=session, registry=registry)
    except ModelError as e:
        return fail(f"{e}\nSee docs/cli/usage.md#models, or `harness --list-models`.")
    except TrifectaError as e:
        return fail(str(e))

    if args.print:
        return run_headless(app, prompt, args.output_format, stdout, stderr)
    return run_repl(app, input_fn=input_fn, first_prompt=prompt)


def entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry()
