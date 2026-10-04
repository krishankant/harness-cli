import pytest

from harnessy.tools.files import file_tools, resolve_inside
from harnessy.tools.registry import ToolRegistry
from harnessy.types import ToolCall


def test_resolve_inside_allows_nested_paths(tmp_path):
    assert resolve_inside(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()
    assert resolve_inside(tmp_path, ".") == tmp_path.resolve()


def test_resolve_inside_rejects_dotdot(tmp_path):
    with pytest.raises(ValueError, match="escapes the workspace"):
        resolve_inside(tmp_path, "../x")


def test_resolve_inside_rejects_absolute_paths(tmp_path):
    with pytest.raises(ValueError, match="escapes the workspace"):
        resolve_inside(tmp_path, "/etc/passwd")


def test_resolve_inside_rejects_symlink_out(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="escapes the workspace"):
        resolve_inside(root, "link/secret.txt")


def registry(root) -> ToolRegistry:
    return ToolRegistry(file_tools(root))


def test_write_then_read_with_line_numbers(tmp_path):
    reg = registry(tmp_path)
    w = reg.call(ToolCall("c1", "write_file", {"path": "notes/a.txt", "content": "one\ntwo\nthree"}))
    assert (w.content, w.is_error) == ("Wrote 13 characters to notes/a.txt", False)
    r = reg.call(ToolCall("c2", "read_file", {"path": "notes/a.txt"}))
    assert r.content == "    1\tone\n    2\ttwo\n    3\tthree"


def test_read_with_offset_limit_and_footer(tmp_path):
    (tmp_path / "ten.txt").write_text("\n".join(f"line {i}" for i in range(1, 11)))
    r = registry(tmp_path).call(ToolCall("c1", "read_file", {"path": "ten.txt", "offset": 3, "limit": 2}))
    assert r.content == "    3\tline 3\n    4\tline 4\n[showing lines 3-4 of 10; call again with offset=5 for more]"


def test_escape_is_an_error_result(tmp_path):
    r = registry(tmp_path).call(ToolCall("c1", "read_file", {"path": "../secret"}))
    assert r.is_error and "escapes the workspace" in r.content


def test_missing_file_is_an_error_result(tmp_path):
    r = registry(tmp_path).call(ToolCall("c1", "read_file", {"path": "nope.txt"}))
    assert r.is_error and "FileNotFoundError" in r.content
