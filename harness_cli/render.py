"""Terminal output: streamed text, one line per tool call, approval prompts, notices.

Colour only when writing to a terminal and NO_COLOR is not set (https://no-color.org)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Callable, TextIO

from harness_cli.permissions import main_argument
from harnessy.types import ToolCall, ToolResult

_CODES = {"dim": "2", "bold": "1", "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36"}


def use_color(out: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(out, "isatty", lambda: False)())


class Spinner:
    """One animated status line ("⠹ Running… 12s · Ctrl-C to interrupt") drawn by a background
    thread while a tool runs or the model is thinking. It waits `delay` seconds before drawing,
    so quick work never flickers, and stop() erases the line before anything else is printed."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    HINT = "Ctrl-C to interrupt"

    def __init__(
        self,
        out: TextIO,
        enabled: bool,
        delay: float = 0.3,
        interval: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        style: Callable[[str], str] = lambda text: text,
    ):
        self.out = out
        self.enabled = enabled
        self.delay = delay
        self.interval = interval
        self.clock = clock
        self.style = style
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._drawn = False

    @property
    def active(self) -> bool:
        return self._thread is not None

    def start(self, label: str) -> None:
        self.stop()
        if not self.enabled:
            return
        self._stop = threading.Event()
        self._drawn = False
        started = self.clock()
        stop = self._stop

        def run() -> None:
            if stop.wait(self.delay):
                return
            frame = 0
            while not stop.is_set():
                elapsed = int(self.clock() - started)
                line = f"{self.FRAMES[frame % len(self.FRAMES)]} {label} {elapsed}s · {self.HINT}"
                with self._lock:
                    if stop.is_set():
                        return
                    self.out.write("\r\033[2K" + self.style(line))
                    self.out.flush()
                    self._drawn = True
                frame += 1
                stop.wait(self.interval)

        self._thread = threading.Thread(target=run, daemon=True, name="harness-spinner")
        self._thread.start()

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        if thread is None:
            return
        self._stop.set()
        thread.join()
        with self._lock:
            if self._drawn:
                self.out.write("\r\033[2K")
                self.out.flush()
                self._drawn = False


def busy_label(call: ToolCall) -> str:
    if call.name == "run_shell":
        return "Running…"
    if call.name == "spawn_subagent":
        return "Subagent working…"
    return "Working…"


def summarize_call(call: ToolCall, limit: int = 90) -> str:
    arg = main_argument(call) or json.dumps(call.arguments, default=str)
    arg = " ".join(arg.split())
    return f"{call.name}({arg if len(arg) <= limit else arg[: limit - 1] + '…'})"


class Renderer:
    def __init__(self, out: TextIO = sys.stdout, color: bool | None = None, input_fn: Callable[[str], str] = input):
        self.out = out
        self.color = use_color(out) if color is None else color
        self.input_fn = input_fn
        self._at_line_start = True
        # Animate only on a real terminal; pipes, files and -p output stay clean.
        animate = bool(getattr(out, "isatty", lambda: False)()) and color is not False
        self.spinner = Spinner(out, enabled=animate, style=lambda text: self.style(text, "dim"))

    def style(self, text: str, *names: str) -> str:
        if not self.color or not names:
            return text
        codes = ";".join(_CODES[n] for n in names)
        return f"\033[{codes}m{text}\033[0m"

    def write(self, text: str) -> None:
        self.spinner.stop()  # every output goes through here, so the spinner never overlaps it
        if not text:
            return
        self.out.write(text)
        self.out.flush()
        self._at_line_start = text.endswith("\n")

    def line(self, text: str = "") -> None:
        self.end_text()
        self.write(text + "\n")

    def end_text(self) -> None:
        if not self._at_line_start:
            self.write("\n")

    # --- events ---

    def busy(self, label: str) -> None:
        """Show the spinner until the next output. Only from a fresh line."""
        if self._at_line_start:
            self.spinner.start(label)

    def busy_for(self, call: ToolCall) -> None:
        self.busy(busy_label(call))

    def idle(self) -> None:
        self.spinner.stop()

    def text(self, delta: str) -> None:
        self.write(delta)

    def tool_start(self, call: ToolCall) -> None:
        self.line(self.style("● ", "cyan") + self.style(summarize_call(call), "bold"))

    def tool_end(self, call: ToolCall, result: ToolResult) -> None:
        lines = result.content.strip().splitlines() or ["(no output)"]
        first = lines[0] if len(lines[0]) <= 110 else lines[0][:109] + "…"
        more = f" (+{len(lines) - 1} lines)" if len(lines) > 1 else ""
        if result.is_error:
            self.line(self.style(f"  ⎿ {first}", "red") + self.style(more, "dim"))
        else:
            self.line(self.style(f"  ⎿ {first}", "dim") + self.style(more, "dim"))

    def preview(self, call: ToolCall) -> list[str]:
        """What the approval prompt shows: the command, or the change a file edit makes."""
        args = call.arguments
        if call.name == "edit_file":
            old = str(args.get("old", "")).splitlines()[:8]
            new = str(args.get("new", "")).splitlines()[:8]
            return [self.style(f"- {line}", "red") for line in old] + [self.style(f"+ {line}", "green") for line in new]
        if call.name == "write_file":
            body = str(args.get("content", "")).splitlines()
            shown = [self.style(f"+ {line}", "green") for line in body[:8]]
            return shown + ([self.style(f"  … {len(body) - 8} more lines", "dim")] if len(body) > 8 else [])
        if call.name == "run_shell":
            return [self.style(f"$ {args.get('command', '')}", "yellow")]
        if call.name == "remember":
            where = "~/.harness/HARNESS.md (every project)" if args.get("scope") == "user" else "HARNESS.md (this project)"
            return [self.style(f"+ - {' '.join(str(args.get('text', '')).split())}", "green"), self.style(f"  saved to {where}, loaded into every future conversation", "dim")]
        return [self.style(json.dumps(args, default=str)[:400], "dim")]

    def ask(self, call: ToolCall) -> str:
        """Ask y/n/a. EOF counts as no; Ctrl-C propagates (the caller cancels the turn)."""
        self.line(self.style("? ", "yellow") + self.style(f"Allow {call.name}", "bold") + f" {self._target(call)}")
        for line in self.preview(call):
            self.line("    " + line)
        while True:
            try:
                answer = self.input_fn(self.style("  [y]es  [n]o  [a]lways for this session › ", "yellow")).strip().lower()
            except EOFError:
                self.line()
                return "n"
            self._at_line_start = True
            if answer in ("y", "yes"):
                return "y"
            if answer in ("n", "no", ""):
                return "n"
            if answer in ("a", "always"):
                return "a"

    @staticmethod
    def _target(call: ToolCall) -> str:
        path = call.arguments.get("path")
        return f"→ {path}" if isinstance(path, str) else ""

    # --- notices ---

    def info(self, text: str) -> None:
        self.line(self.style(text, "dim"))

    def note(self, text: str) -> None:
        self.line(text)

    def warn(self, text: str) -> None:
        self.line(self.style(text, "yellow"))

    def error(self, text: str) -> None:
        self.line(self.style(text, "red"))
