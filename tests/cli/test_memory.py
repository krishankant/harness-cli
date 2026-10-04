import pytest

from harness_cli.config import Settings
from harness_cli.instructions import build_system_prompt
from harness_cli.memory import MAX_CHARS, add_memory, memory_file, memory_lines, memory_tool
from harness_cli.permissions import policy_for
from harnessy.tools.registry import ToolRegistry
from harnessy.types import ToolCall


def test_creates_file_with_memory_section(workspace):
    path = memory_file(workspace, "project")
    assert path == workspace / "HARNESS.md"
    assert add_memory(path, "Run tests with uv run pytest") == "Remembered in HARNESS.md: Run tests with uv run pytest"
    assert path.read_text() == "## Memory\n\n- Run tests with uv run pytest\n"


def test_appends_inside_existing_section_not_at_eof(workspace):
    path = workspace / "HARNESS.md"
    path.write_text("# My project\n\nIntro.\n\n## Memory\n\n- first\n\n## Layout\n\nsrc/ holds code.\n")
    add_memory(path, "second")
    assert path.read_text() == "# My project\n\nIntro.\n\n## Memory\n\n- first\n- second\n\n## Layout\n\nsrc/ holds code.\n"
    assert memory_lines(path) == ["first", "second"]


def test_adds_section_to_file_without_one(workspace):
    path = workspace / "HARNESS.md"
    path.write_text("# Notes\n\nUse uv.")
    add_memory(path, "fact")
    assert path.read_text() == "# Notes\n\nUse uv.\n\n## Memory\n\n- fact\n"


def test_duplicate_and_cleanup(workspace):
    path = workspace / "HARNESS.md"
    add_memory(path, "  multi\nline   fact  ")
    assert memory_lines(path) == ["multi line fact"]
    assert add_memory(path, "multi line fact").startswith("Already remembered")
    assert memory_lines(path) == ["multi line fact"]


def test_rejects_empty_and_too_long(workspace):
    path = workspace / "HARNESS.md"
    with pytest.raises(ValueError, match="empty"):
        add_memory(path, "   ")
    with pytest.raises(ValueError, match=str(MAX_CHARS)):
        add_memory(path, "x" * (MAX_CHARS + 1))
    assert not path.exists()


def test_user_scope_goes_to_harness_home(workspace, harness_home):
    reg = ToolRegistry([memory_tool(workspace)])
    out = reg.call(ToolCall("1", "remember", {"text": "I prefer small commits", "scope": "user"}))
    assert not out.is_error
    assert memory_lines(harness_home / "HARNESS.md") == ["I prefer small commits"]
    assert not (workspace / "HARNESS.md").exists()


def test_memory_reaches_the_system_prompt(workspace, harness_home):
    add_memory(memory_file(workspace, "project"), "tests need Docker")
    add_memory(memory_file(workspace, "user"), "answer briefly")
    prompt = build_system_prompt(workspace, Settings(), ["remember"])
    assert "tests need Docker" in prompt and "answer briefly" in prompt


@pytest.mark.parametrize("mode, decision", [("default", "ask"), ("accept-edits", "ask"), ("plan", "deny"), ("bypass", "allow")])
def test_memory_permission_kind(mode, decision):
    assert policy_for(mode, ["remember"])["remember"] == decision
