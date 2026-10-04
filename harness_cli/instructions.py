"""The system prompt: a base prompt, facts about the environment, then the user's and the
project's instruction files (HARNESS.md, AGENTS.md, CLAUDE.md), then any appended prompt."""

from __future__ import annotations

import datetime
import platform
from pathlib import Path
from typing import Iterable

from harness_cli.config import Settings, harness_home

INSTRUCTION_FILES = ("HARNESS.md", "AGENTS.md", "CLAUDE.md")
MAX_FILE_CHARS = 20_000

BASE_PROMPT = """You are harness, a coding agent running in the user's terminal. You help with software \
engineering tasks in the current workspace: reading and explaining code, fixing bugs, adding features, \
running tests and commands.

How to work:
- Look before you change: use list_files, search_files and read_file to find the relevant code.
- Make focused edits with edit_file (exact text, matching once); use write_file for new files.
- Verify with run_shell (tests, linters, builds) when it makes sense, and report what happened honestly.
- For a task with several steps, keep a plan with the todo tool and complete items as you go.
- Hand a large, self-contained investigation to spawn_subagent to keep your own context small.
- Some actions need the user's approval. If one is declined, do not retry it; ask what they want instead.
- Keep answers short and concrete. Refer to code as path:line. Use Markdown sparingly."""


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(errors="replace")
    return text if len(text) <= MAX_FILE_CHARS else text[:MAX_FILE_CHARS] + "\n[truncated]"


def instruction_sources(workspace: Path) -> list[Path]:
    """Instruction files that exist, user-level first."""
    candidates = [harness_home() / "HARNESS.md", *(Path(workspace) / name for name in INSTRUCTION_FILES)]
    return [p for p in candidates if p.is_file()]


def build_system_prompt(workspace: Path, settings: Settings, tool_names: Iterable[str]) -> str:
    parts = [settings.system_prompt or BASE_PROMPT]
    is_git = (Path(workspace) / ".git").exists()
    parts.append(
        "Environment:\n"
        f"- Workspace (all paths are relative to it): {workspace}\n"
        f"- Git repository: {'yes' if is_git else 'no'}\n"
        f"- Platform: {platform.system()} {platform.release()}\n"
        f"- Date: {datetime.date.today().isoformat()}\n"
        f"- Tools: {', '.join(tool_names) or 'none'}"
    )
    for path in instruction_sources(workspace):
        text = _read(path)
        if text:
            parts.append(f"Instructions from {path}:\n{text}")
    if settings.append_system_prompt:
        parts.append(settings.append_system_prompt)
    return "\n\n".join(parts)
