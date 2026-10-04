from harness_cli.config import Settings
from harnessy.approvals import ApprovalHook
from harness_cli.tools import KIND, SessionTodo, build_tools
from harnessy.models.scripted import ScriptedModel, text_reply
from harnessy.tools.registry import ToolRegistry
from harnessy.types import ToolCall


def registry(workspace, **settings):
    guard = ApprovalHook({"run_shell": "ask"}, approver=lambda call: True)
    tools = build_tools(workspace, Settings(sandbox="off", **settings), SessionTodo(), ScriptedModel([text_reply("sub done")]), hooks=[guard])
    return ToolRegistry(tools)


def call(reg, name, **args):
    return reg.call(ToolCall("1", name, args))


def test_tool_set_and_kinds(workspace):
    names = registry(workspace).specs()
    assert {s.name for s in names} == set(KIND)
    assert KIND["read_file"] == "read" and KIND["edit_file"] == "edit" and KIND["run_shell"] == "execute"


def test_list_files_skips_noise(workspace):
    (workspace / "src").mkdir()
    (workspace / "src" / "a.py").write_text("x")
    (workspace / "b.txt").write_text("y")
    for junk in (".git", ".venv", "node_modules", "__pycache__"):
        (workspace / junk).mkdir()
        (workspace / junk / "z.py").write_text("")
    out = call(registry(workspace), "list_files").content
    assert out.splitlines() == ["b.txt", "src/a.py"]
    assert call(registry(workspace), "list_files", pattern="**/*.py").content == "src/a.py"


def test_search_finds_lines(workspace):
    (workspace / "a.py").write_text("def foo():\n    return 1\n")
    (workspace / "b.py").write_text("foo()\n")
    out = call(registry(workspace), "search_files", pattern=r"foo\(").content
    assert out.splitlines() == ["a.py:1: def foo():", "b.py:1: foo()"]


def test_search_skips_binary(workspace):
    (workspace / "blob.bin").write_bytes(b"\x00\xff foo \x00")
    (workspace / "latin.txt").write_bytes("caf\xe9 foo".encode("latin-1"))
    out = call(registry(workspace), "search_files", pattern="foo")
    assert not out.is_error
    assert out.content.splitlines() == ["latin.txt:1: caf� foo"]


def test_search_no_match_and_bad_regex(workspace):
    (workspace / "a.txt").write_text("hello")
    assert call(registry(workspace), "search_files", pattern="zzz").content == "No matches for 'zzz'."
    assert call(registry(workspace), "search_files", pattern="(").is_error


def test_file_tools_stay_inside(workspace):
    reg = registry(workspace)
    assert call(reg, "write_file", path="../outside.txt", content="x").is_error
    assert call(reg, "list_files", path="..").is_error
    assert not (workspace.parent / "outside.txt").exists()


def test_run_shell_reports_exit_code(workspace):
    out = call(registry(workspace), "run_shell", command="echo hi; exit 3").content
    assert out.startswith("exit code 3") and "hi" in out


def test_todo_persists_across_runs():
    todo = SessionTodo()
    todo.apply("add", "step one")
    todo.on_start(None, "next turn")
    assert "step one" in todo.render()


def test_subagent_runs(workspace):
    out = call(registry(workspace), "spawn_subagent", task="look around")
    assert out.content == "sub done"


def test_subagent_without_guard_is_refused(workspace):
    tools = build_tools(workspace, Settings(sandbox="off"), SessionTodo(), ScriptedModel([text_reply("x")]), hooks=[])
    out = ToolRegistry(tools).call(ToolCall("1", "spawn_subagent", {"task": "t"}))
    assert out.is_error and "lethal trifecta" in out.content
