"""Code tools (week 8): read, write and edit files, and run the tests in the sandbox."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from harnessy.tools.files import file_tools, resolve_inside
from harnessy.tools.sandbox import run_command
from harnessy.tools.schema import tool
from harnessy.types import Tool

# --- Week 8 exercise -------------------------------------------------------------------


def edit_text(text: str, old: str, new: str) -> str:
    """Replace old with new in text, where old must appear EXACTLY once.
    - old empty -> ValueError("old text must not be empty")
    - not found -> ValueError mentioning "not found" (tell the model to read the file again
      and copy the exact text, spaces included)
    - n > 1 times -> ValueError(f"old text appears {n} times; ...") asking for more context.
    One unique match is what makes an edit safe to apply blind."""
    if not old:
        raise ValueError("old text must not be empty")
    count = text.count(old)
    if count == 0:
        raise ValueError("old text not found; read the file again and copy the exact text, including spaces")
    if count > 1:
        raise ValueError(f"old text appears {count} times; include more surrounding lines so it matches once")
    return text.replace(old, new, 1)


# --- Given -----------------------------------------------------------------------------


def code_tools(root: str | Path, test_timeout_s: float = 120.0) -> list[Tool]:
    read_file, write_file = file_tools(root)

    @tool
    def edit_file(path: str, old: str, new: str) -> str:
        """Replace one exact piece of text in a file. old must match exactly once, including spaces and line breaks.

        Args:
            path: File path, relative to the workspace root.
            old: The exact text to replace.
            new: The text to put in its place.
        """
        target = resolve_inside(root, path)
        target.write_text(edit_text(target.read_text(), old, new))
        return f"Edited {path}"

    # Running tests runs code the model may have written: a shell by another name (week 7).
    @tool(timeout_s=test_timeout_s + 10, tags={"private_data", "untrusted_input", "external_send"})
    def run_tests(args: str = "") -> str:
        """Run the project's tests with pytest and return the exit code and the end of the output.

        Args:
            args: Extra pytest arguments, for example "-k parser" or "test_parser.py".
        """
        result = run_command(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *shlex.split(args)],
            Path(root), test_timeout_s, max_output=1_000_000,
        )
        tail = result.output[-3000:]
        if result.timed_out:
            return f"tests timed out after {test_timeout_s:g}s\n{tail}"
        return f"exit code {result.exit_code}\n{tail}"

    return [read_file, write_file, edit_file, run_tests]
