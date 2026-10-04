"""Shell commands: harnessy's run_command (scrubbed environment, real timeout, capped output),
plus macOS Seatbelt on top when it is available (no network, writes only in the workspace).
The two layers and their limits are explained in docs/sandbox.md."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from harness_cli.config import harness_home
from harnessy.tools.sandbox import CommandResult, run_command

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
WRITABLE = ("/private/tmp", "/private/var/folders", "/dev")
SECRET_DIRS = (".ssh", ".aws", ".gnupg", ".config/gh", ".netrc")


def sandbox_available() -> bool:
    return sys.platform == "darwin" and shutil.which(SANDBOX_EXEC) is not None


def _quote(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(workspace: Path) -> str:
    """Allow everything except: the network, writes outside the workspace and temp folders,
    and reads of credential folders. The workspace is resolved, because Seatbelt matches real
    paths (/tmp is really /private/tmp on macOS)."""
    ws = Path(workspace).resolve()
    writable = " ".join(f"(subpath {_quote(p)})" for p in (ws, *WRITABLE))
    secrets = " ".join(f"(subpath {_quote(Path.home() / d)})" for d in SECRET_DIRS)
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            "(deny file-write*)",
            f"(allow file-write* {writable})",
            f"(deny file-read* {secrets} (subpath {_quote(harness_home().resolve())}))",
        ]
    )


def run_sandboxed(command: str, workspace: Path, timeout_s: float, mode: str, max_output: int = 20_000) -> CommandResult:
    """Run a shell command line in the workspace. mode "workspace-write" adds Seatbelt where it
    exists; "off" (or no Seatbelt) runs with run_command's hygiene only."""
    if mode == "workspace-write" and sandbox_available():
        argv = [SANDBOX_EXEC, "-p", seatbelt_profile(workspace), "/bin/sh", "-c", command]
        return run_command(argv, workspace, timeout_s, max_output=max_output)
    return run_command(command, workspace, timeout_s, max_output=max_output)


def describe(mode: str) -> str:
    if mode == "off":
        return "off (environment scrubbed, timeout; no OS isolation)"
    if sandbox_available():
        return "workspace-write (Seatbelt: no network, writes only inside the workspace)"
    return "workspace-write requested, but Seatbelt is not available here: hygiene only"
