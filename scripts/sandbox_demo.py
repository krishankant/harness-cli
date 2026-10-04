"""What the sandbox stops and what it doesn't: the same probes run with run_command alone, then
inside the operating system's own sandbox (Seatbelt, macOS only). No keys, no model calls.

Run from the repo root:  uv run python -m scripts.sandbox_demo
Against the reference solutions:  HARNESSY_IMPL=solutions uv run python -m scripts.sandbox_demo
See docs/sandbox.md for the walk-through.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from harnessy.tools.sandbox import run_command

FAKE_KEY = "sk-demo-not-a-real-key"


def seatbelt_profile(workspace: Path) -> str:
    """Allow everything, then take away: the network, writes outside the workspace, reads of
    your home folder and of the workspace's neighbours."""
    home = Path.home().resolve()
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-write* (require-not (subpath "{workspace}")))
(deny file-read* (subpath "{home}"))
(deny file-read* (require-all (subpath "{workspace.parent}") (require-not (subpath "{workspace}"))))"""


def last_line(text: str, limit: int = 58) -> str:
    lines = text.strip().splitlines()
    line = lines[-1] if lines else "(no output)"
    return line if len(line) <= limit else line[: limit - 3] + "..."


def hygiene(ws: Path) -> None:
    print("\nWhat run_command does on its own\n")
    os.environ["OPENAI_API_KEY"] = FAKE_KEY
    names = sorted(line.split("=", 1)[0] for line in run_command("env", ws).output.splitlines() if "=" in line)
    leaked = FAKE_KEY in run_command("env", ws).output
    print(f"  environment   the command sees only: {', '.join(names)}")
    print(f"                OPENAI_API_KEY was set outside; inside it is {'VISIBLE' if leaked else 'gone'}")

    start = time.monotonic()
    r = run_command("sleep 30 & sleep 30", ws, timeout_s=1)
    print(f"  time limit    'sleep 30 & sleep 30' with timeout_s=1: killed={r.timed_out} after {time.monotonic() - start:.1f}s")

    r = run_command("yes", ws, max_bytes=1_000_000)
    print(f"  output flood  'yes' with max_bytes=1,000,000: {last_line(r.output, 80)}")

    r = run_command("read answer; echo got: $answer", ws, timeout_s=2)
    print(f"  input         'read answer' gets no input and moves on: timed_out={r.timed_out}, {last_line(r.output)!r}")


PROBES = {
    "read a neighbour": "cat ../secret.txt",
    "list your home": "ls \"$REAL_HOME\" 2>&1 >/dev/null | head -1; ls \"$REAL_HOME\" 2>/dev/null | wc -l | xargs printf '%s entries listed\\n'",
    "write outside": "echo x > ../planted.txt && echo wrote ../planted.txt",
    "write inside": "echo hello > note.txt && cat note.txt",
    "reach the network": "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3); print('connected to 1.1.1.1')\"",
    "read system files": "head -c 40 /etc/hosts | head -1",
}


def isolation(ws: Path) -> None:
    (ws.parent / "secret.txt").write_text("the secret next door")
    env = {"REAL_HOME": str(Path.home())}
    seatbelt = sys.platform == "darwin" and shutil.which("sandbox-exec")
    profile = seatbelt_profile(ws) if seatbelt else ""
    print(f"\nThe same commands, without and with the OS sandbox{'' if seatbelt else ' (Seatbelt needs macOS: skipped)'}\n")
    print(f"  {'probe':<19} {'run_command alone':<60} {'+ Seatbelt' if seatbelt else ''}")
    for name, cmd in PROBES.items():
        plain = last_line(run_command(cmd, ws, timeout_s=10, env=env).output)
        boxed = last_line(run_command(["sandbox-exec", "-p", profile, "/bin/sh", "-c", cmd], ws, timeout_s=10, env=env).output) if seatbelt else ""
        print(f"  {name:<19} {plain:<60} {boxed}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = (Path(tmp) / "workspace").resolve()
        ws.mkdir()
        hygiene(ws)
        isolation(ws)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
