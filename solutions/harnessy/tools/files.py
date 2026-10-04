"""read_file and write_file, confined to one workspace folder (week 3). The confinement is
code, not a prompt: a path outside the workspace is an error result, whatever the model says."""

from __future__ import annotations

from pathlib import Path

from harnessy.tools.schema import tool
from harnessy.types import Tool


# --- Week 3 exercise -------------------------------------------------------------------


def resolve_inside(root: str | Path, path: str) -> Path:
    """Resolve path (relative to root) to an absolute Path, following '..' and symlinks
    (Path.resolve does both). If the result is not root itself or inside it, raise
    ValueError(f"path escapes the workspace: {path}"). An absolute path like /etc/passwd
    must fail too (root / "/etc/passwd" is just /etc/passwd).
    """
    root_path = Path(root).resolve()
    target = (root_path / path).resolve()
    if target != root_path and root_path not in target.parents:
        raise ValueError(f"path escapes the workspace: {path}")
    return target


# --- Given -----------------------------------------------------------------------------


def file_tools(root: str | Path) -> list[Tool]:
    """read_file and write_file tools that only touch files inside root."""

    @tool(tags={"private_data"})
    def read_file(path: str, offset: int = 1, limit: int = 200) -> str:
        """Read a text file from the workspace, with line numbers.

        Args:
            path: File path, relative to the workspace root.
            offset: First line to show (1-based).
            limit: Maximum number of lines to show.
        """
        target = resolve_inside(root, path)
        if not target.is_file():
            raise FileNotFoundError(f"no such file in the workspace: {path}")
        lines = target.read_text(errors="replace").splitlines()
        start = max(offset, 1) - 1
        chunk = lines[start : start + limit]
        out = "\n".join(f"{start + i + 1:>5}\t{line}" for i, line in enumerate(chunk))
        if start + len(chunk) < len(lines):
            end = start + len(chunk)
            out += f"\n[showing lines {start + 1}-{end} of {len(lines)}; call again with offset={end + 1} for more]"
        return out or "(empty file)"

    @tool
    def write_file(path: str, content: str) -> str:
        """Write text to a file in the workspace, replacing it if it exists. Creates folders as needed.

        Args:
            path: File path, relative to the workspace root.
            content: The full text to write.
        """
        target = resolve_inside(root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"Wrote {len(content)} characters to {path}"

    return [read_file, write_file]
