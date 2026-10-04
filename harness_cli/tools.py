"""The coding agent's tools: harnessy's file tools plus listing, searching, a sandboxed shell,
a todo list, subagents and MCP servers."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Iterable

from harness_cli.config import Settings
from harness_cli.memory import memory_tool
from harness_cli.sandbox import run_sandboxed
from harnessy.hooks import Hook
from harnessy.mcp import McpClient, mcp_tools
from harnessy.models.base import Model
from harnessy.subagents import subagent_tool
from harnessy.todo import TodoList
from harnessy.tools.code import code_tools
from harnessy.tools.files import resolve_inside
from harnessy.tools.schema import tool
from harnessy.types import Tool

# Every built-in tool and what kind of action it is; permissions.py decides per kind.
KIND = {
    "read_file": "read",
    "list_files": "read",
    "search_files": "read",
    "todo": "read",
    "write_file": "edit",
    "edit_file": "edit",
    "run_shell": "execute",
    "spawn_subagent": "agent",
    "remember": "memory",
}
IGNORED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".harness", "dist", "build"}
MAX_LISTED = 500
MAX_MATCHES = 200
MAX_SEARCH_BYTES = 2_000_000


class SessionTodo(TodoList):
    """harnessy's TodoList, kept for the whole conversation instead of reset every run
    (each chat turn is one run). /clear calls reset()."""

    def on_start(self, agent: Any, task: str) -> None:
        pass

    def reset(self) -> None:
        self.items = []


def _walk(root: Path, start: Path) -> Iterable[Path]:
    for path in sorted(start.rglob("*")):
        rel = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts) or not path.is_file():
            continue
        yield path


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def search_tools(root: Path) -> list[Tool]:
    @tool(tags={"private_data"})
    def list_files(pattern: str = "**/*", path: str = ".") -> str:
        """List files in the workspace that match a glob pattern, skipping .git, virtualenvs, node_modules and caches.

        Args:
            pattern: Glob relative to path, for example "**/*.py" or "*.md".
            path: Folder to list, relative to the workspace root.
        """
        start = resolve_inside(root, path)
        if not start.is_dir():
            raise NotADirectoryError(f"not a folder in the workspace: {path}")
        bare = pattern[3:] if pattern.startswith("**/") else None
        hits = []
        for p in _walk(Path(root).resolve(), start):
            rel = p.relative_to(start).as_posix()
            if fnmatch.fnmatch(rel, pattern) or (bare is not None and fnmatch.fnmatch(rel, bare)):
                hits.append(p.relative_to(Path(root).resolve()).as_posix())
        if not hits:
            return f"No files match '{pattern}'."
        more = f"\n[{len(hits) - MAX_LISTED} more not shown; narrow the pattern]" if len(hits) > MAX_LISTED else ""
        return "\n".join(hits[:MAX_LISTED]) + more

    @tool(tags={"private_data"})
    def search_files(pattern: str, path: str = ".", glob: str | None = None) -> str:
        """Search file contents with a regular expression and return matching lines as path:line: text.

        Args:
            pattern: A Python regular expression, for example "def \\w+_test" or "TODO".
            path: Folder to search, relative to the workspace root.
            glob: Only search files whose path matches this glob, for example "*.py".
        """
        regex = re.compile(pattern)
        base = Path(root).resolve()
        start = resolve_inside(root, path)
        files = [start] if start.is_file() else list(_walk(base, start))
        matches: list[str] = []
        for f in files:
            rel = f.relative_to(base).as_posix()
            if glob and not (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(f.name, glob)):
                continue
            if f.stat().st_size > MAX_SEARCH_BYTES:
                continue
            data = f.read_bytes()
            if _is_binary(data):
                continue
            for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{n}: {line.strip()[:200]}")
                    if len(matches) >= MAX_MATCHES:
                        return "\n".join(matches) + f"\n[stopped at {MAX_MATCHES} matches; narrow the search]"
        return "\n".join(matches) or f"No matches for '{pattern}'."

    return [list_files, search_files]


def shell_tool(root: Path, settings: Settings) -> Tool:
    timeout = settings.shell_timeout_s

    # A shell can read files, read untrusted output and reach the network: all three legs.
    @tool(timeout_s=timeout + 10, tags={"private_data", "untrusted_input", "external_send"})
    def run_shell(command: str) -> str:
        """Run a shell command in the workspace folder and return its exit code and output. Use it for tests, builds, git and other CLI tools. The environment is scrubbed and the command may be sandboxed (no network, writes only inside the workspace).

        Args:
            command: The command line, run with /bin/sh.
        """
        result = run_sandboxed(command, Path(root), timeout, settings.sandbox)
        if result.timed_out:
            return f"timed out after {timeout:g}s; the process was killed\n{result.output}"
        return f"exit code {result.exit_code}\n{result.output}"

    return run_shell


def build_tools(workspace: Path, settings: Settings, todo: TodoList, model: Model, hooks: Iterable[Hook] = ()) -> list[Tool]:
    """The built-in tools. hooks (the approval hook) also guard every subagent."""
    root = Path(workspace).resolve()
    read_file, write_file, edit_file, _run_tests = code_tools(root)
    worker_tools = [read_file, *search_tools(root), write_file, edit_file, shell_tool(root, settings)]
    subagent = subagent_tool(model, worker_tools, hooks=hooks, max_steps=20)
    return [*worker_tools, todo.tool(), memory_tool(root), subagent]


def start_mcp(servers: dict[str, Any], workspace: Path) -> tuple[list[Tool], list[McpClient], list[str]]:
    """Start each configured MCP server. Returns its tools (named <server>__<tool>), the clients to
    close on exit, and one error line per server that failed (the session goes on without it)."""
    tools: list[Tool] = []
    clients: list[McpClient] = []
    errors: list[str] = []
    for name, cfg in servers.items():
        command = cfg.get("command")
        if isinstance(command, str):
            command = [command, *cfg.get("args", [])]
        if not command:
            errors.append(f"MCP server '{name}': no command")
            continue
        try:
            client = McpClient.stdio(list(command), env=cfg.get("env"), cwd=str(cfg.get("cwd") or workspace))
            client.connect()
            tools.extend(mcp_tools(client, prefix=name))
            clients.append(client)
        except Exception as e:  # a broken server must not stop the CLI
            errors.append(f"MCP server '{name}' failed to start: {type(e).__name__}: {e}")
    return tools, clients, errors
