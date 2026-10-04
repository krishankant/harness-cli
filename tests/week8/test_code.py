import pytest

from harnessy.tools.code import code_tools, edit_text
from harnessy.tools.registry import ToolRegistry
from harnessy.types import ToolCall


def test_edit_text():
    assert edit_text("a = 1\nb = 2\n", "b = 2", "b = 3") == "a = 1\nb = 3\n"
    with pytest.raises(ValueError, match="not found"):
        edit_text("abc", "x", "y")
    with pytest.raises(ValueError, match="appears 2 times"):
        edit_text("a-a", "a", "b")
    with pytest.raises(ValueError, match="empty"):
        edit_text("abc", "", "y")


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "calc.py").write_text("def double(x):\n    return x + x + 1\n")
    (tmp_path / "test_calc.py").write_text("from calc import double\n\n\ndef test_double():\n    assert double(3) == 6\n")
    return tmp_path


def test_edit_and_run_tests(repo):
    reg = ToolRegistry(code_tools(repo, test_timeout_s=60))
    assert [s.name for s in reg.specs()] == ["read_file", "write_file", "edit_file", "run_tests"]
    assert reg.call(ToolCall("c1", "run_tests", {})).content.startswith("exit code 1")
    edited = reg.call(ToolCall("c2", "edit_file", {"path": "calc.py", "old": "x + x + 1", "new": "x + x"}))
    assert edited.content == "Edited calc.py"
    passed = reg.call(ToolCall("c3", "run_tests", {})).content
    assert passed.startswith("exit code 0") and "1 passed" in passed


def test_edit_mistakes_are_error_results(repo):
    r = ToolRegistry(code_tools(repo)).call(ToolCall("c1", "edit_file", {"path": "calc.py", "old": "nope", "new": "x"}))
    assert r.is_error and "not found" in r.content


def test_run_tests_is_tagged_like_a_shell(repo):
    run_tests = code_tools(repo)[3]
    assert run_tests.name == "run_tests"
    assert run_tests.tags == frozenset({"private_data", "untrusted_input", "external_send"})
