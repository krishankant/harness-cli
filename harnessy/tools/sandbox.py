"""A sandbox for commands (week 7): a subprocess in the workspace, with a scrubbed environment,
a time limit that really kills, and capped output. POSIX only (macOS, Linux).

Not a security boundary on its own: the command still runs as you. Docker is the stretch."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from harnessy.tools.registry import truncate
from harnessy.tools.schema import tool
from harnessy.types import Tool

SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TERM")


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None  # None if it was killed for taking too long
    output: str  # stdout and stderr together
    timed_out: bool


# --- Week 7 exercise -------------------------------------------------------------------


def run_command(
    command: list[str] | str,
    workdir: str | Path,
    timeout_s: float = 30.0,
    max_output: int = 10_000,
    env: dict[str, str] | None = None,
    max_bytes: int = 10_000_000,
) -> CommandResult:
    """Run command in workdir and return what happened. Never raises for a failing command.

    - A list runs directly; a str runs through /bin/sh (shell=isinstance(command, str)).
    - Environment: ONLY the SAFE_ENV_KEYS that exist in os.environ, plus HOME=str(workdir),
      plus env. Your API keys must not reach the command.
    - Output (stdout and stderr together, stderr=subprocess.STDOUT) goes to a
      tempfile.TemporaryFile, not a pipe: a pipe holds everything in memory, and a descendant
      that keeps it open would make you wait forever. stdin=subprocess.DEVNULL,
      start_new_session=True (the command gets its own process group).
    - Poll every 0.02 s (proc.poll()). Kill the whole group (os.killpg(proc.pid, signal.SIGKILL);
      ignore ProcessLookupError) and proc.wait() if the time is up (timed_out=True) or the file
      has grown past max_bytes (os.fstat(file.fileno()).st_size). A command stopped either way
      has exit_code None.
    - Read the file back, decode UTF-8 with errors="replace", truncate(output, max_output)
      (week 3), and if it was stopped for size append
      "\n[output limit of {max_bytes:,} bytes reached; the process was killed]".
    """
    full_env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    full_env["HOME"] = str(workdir)
    full_env.update(env or {})
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(
            command,
            cwd=workdir,
            env=full_env,
            shell=isinstance(command, str),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_s
        timed_out = flooded = False
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
            elif os.fstat(out.fileno()).st_size > max_bytes:
                flooded = True
            else:
                time.sleep(0.02)
                continue
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            break
        out.seek(0)
        output = truncate(out.read().decode("utf-8", errors="replace"), max_output)
    if flooded:
        output += f"\n[output limit of {max_bytes:,} bytes reached; the process was killed]"
    stopped = timed_out or flooded
    return CommandResult(None if stopped else proc.returncode, output, timed_out)


# --- Given -----------------------------------------------------------------------------


def shell_tool(root: str | Path, timeout_s: float = 30.0) -> Tool:
    """A run_shell tool confined to root. Tagged with all three trifecta legs: a shell can read
    your files, read untrusted output, and reach the network."""

    @tool(timeout_s=timeout_s + 5, tags={"private_data", "untrusted_input", "external_send"})
    def run_shell(command: str) -> str:
        """Run a shell command in the workspace folder and return its exit code and output. Only PATH and a few locale variables are passed in.

        Args:
            command: The command line, run with /bin/sh.
        """
        result = run_command(command, Path(root), timeout_s)
        if result.timed_out:
            return f"timed out after {timeout_s:g}s; the process was killed\n{result.output}"
        return f"exit code {result.exit_code}\n{result.output}"

    return run_shell
