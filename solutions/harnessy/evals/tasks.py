"""Eval tasks (week 5): one YAML file per task, checked when it is loaded so a typo in a task
fails loudly instead of silently scoring zero."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TOOLSETS = ("files", "memory")
DIFFICULTIES = ("easy", "medium", "hard")
CHECK_TYPES = (
    "file_exists", "file_contains", "file_lacks", "answer_contains", "answer_matches", "json_valid", "rubric",
    "citations", "command_succeeds",  # week 8
)
AGENT_NAMES = ("research", "code", "data")  # week 8
_KEYS = {"id", "prompt", "difficulty", "checks", "files", "toolsets", "max_steps", "system", "agent"}


class TaskError(ValueError):
    pass


@dataclass(frozen=True)
class EvalTask:
    id: str
    prompt: str
    difficulty: str
    checks: tuple[dict[str, Any], ...]
    files: dict[str, str] = field(default_factory=dict)
    toolsets: tuple[str, ...] = ()
    max_steps: int = 10
    system: str | None = None
    agent: str | None = None  # week 8: build the trial with this capstone agent


# --- Week 5 exercise -------------------------------------------------------------------


def load_task(path: str | Path) -> EvalTask:
    """Read one task file with yaml.safe_load and check it. Every problem raises
    TaskError(f"{path.name}: <problem>"), with these problems (checked in this order):

    - not valid YAML                      -> "not valid YAML (<error>)"
    - not a mapping                       -> "must be a mapping of keys to values"
    - id, prompt, difficulty or checks absent -> "missing '<key>'"
    - a key outside _KEYS                 -> "unknown keys: <sorted, joined ', '>"
    - difficulty not in DIFFICULTIES      -> "difficulty must be one of easy, medium, hard"
    - checks not a non-empty list         -> "'checks' must be a non-empty list"
    - check i (1-based) not a dict with a type in CHECK_TYPES
                                          -> "check <i> needs a 'type' from: <CHECK_TYPES joined ', '>"
    - toolsets (default []) not all in TOOLSETS -> "unknown toolsets: <bad ones joined ', '>"
    - files (default {}) not a dict of str -> "'files' must map paths to text"
    - max_steps (default 10) not an int >= 1 (bool doesn't count) -> "'max_steps' must be a positive integer"
    - agent (default None; week 8) not in AGENT_NAMES -> "unknown agent: <agent>"
    Return EvalTask(str(id), str(prompt), difficulty, tuple(checks), dict(files), tuple(toolsets),
    max_steps, system or None, agent).
    """
    path = Path(path)

    def fail(problem: str) -> None:
        raise TaskError(f"{path.name}: {problem}")

    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        fail(f"not valid YAML ({e})")
    if not isinstance(data, dict):
        fail("must be a mapping of keys to values")
    for key in ("id", "prompt", "difficulty", "checks"):
        if key not in data:
            fail(f"missing '{key}'")
    unknown = set(data) - _KEYS
    if unknown:
        fail(f"unknown keys: {', '.join(sorted(unknown))}")
    if data["difficulty"] not in DIFFICULTIES:
        fail(f"difficulty must be one of {', '.join(DIFFICULTIES)}")
    checks = data["checks"]
    if not isinstance(checks, list) or not checks:
        fail("'checks' must be a non-empty list")
    for i, check in enumerate(checks, start=1):
        if not isinstance(check, dict) or check.get("type") not in CHECK_TYPES:
            fail(f"check {i} needs a 'type' from: {', '.join(CHECK_TYPES)}")
    toolsets = data.get("toolsets") or []
    bad = [t for t in toolsets if t not in TOOLSETS]
    if bad:
        fail(f"unknown toolsets: {', '.join(map(str, bad))}")
    files = data.get("files") or {}
    if not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
        fail("'files' must map paths to text")
    max_steps = data.get("max_steps", 10)
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        fail("'max_steps' must be a positive integer")
    agent = data.get("agent")
    if agent is not None and agent not in AGENT_NAMES:
        fail(f"unknown agent: {agent}")
    return EvalTask(
        str(data["id"]), str(data["prompt"]), data["difficulty"], tuple(checks), dict(files), tuple(toolsets),
        max_steps, data.get("system") or None, agent,
    )


# --- Given -----------------------------------------------------------------------------


def load_tasks(folder: str | Path, select: str | None = None) -> list[EvalTask]:
    """Every *.yaml task in folder and its sub-folders, sorted by path. select keeps one difficulty or the ids
    starting with it. Duplicate ids raise TaskError."""
    tasks = [load_task(p) for p in sorted(Path(folder).rglob("*.yaml"))]
    seen: set[str] = set()
    for t in tasks:
        if t.id in seen:
            raise TaskError(f"duplicate task id: {t.id}")
        seen.add(t.id)
    if select:
        tasks = [t for t in tasks if t.difficulty == select or t.id.startswith(select)]
    return tasks
