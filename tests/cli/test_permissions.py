import pytest

from harness_cli.permissions import PermissionHook, Rule, policy_for
from harnessy.hooks import Block
from harnessy.safety import check_trifecta
from harnessy.tools.sandbox import shell_tool
from harnessy.types import ToolCall

TOOLS = ["read_file", "list_files", "search_files", "todo", "write_file", "edit_file", "run_shell", "spawn_subagent", "notes__add"]


def shell(cmd):
    return ToolCall("1", "run_shell", {"command": cmd})


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("default", {"read_file": "allow", "write_file": "ask", "run_shell": "ask", "spawn_subagent": "allow", "notes__add": "ask"}),
        ("accept-edits", {"read_file": "allow", "write_file": "allow", "run_shell": "ask", "spawn_subagent": "allow", "notes__add": "ask"}),
        ("plan", {"read_file": "allow", "write_file": "deny", "run_shell": "deny", "spawn_subagent": "deny", "notes__add": "deny"}),
        ("bypass", {"read_file": "allow", "write_file": "allow", "run_shell": "ask", "spawn_subagent": "allow", "notes__add": "ask"}),
    ],
)
def test_mode_table(mode, expected):
    policy = policy_for(mode, TOOLS)
    assert {k: policy[k] for k in expected} == expected


def test_rule_matching():
    assert Rule.parse("run_shell(git *)").matches(shell("git status"))
    assert not Rule.parse("run_shell(git *)").matches(shell("rm -rf /"))
    assert Rule.parse("run_shell").matches(shell("anything"))
    assert Rule.parse("write_file(.env*)").matches(ToolCall("1", "write_file", {"path": ".env.local", "content": ""}))
    assert Rule.parse("notes__*").matches(ToolCall("1", "notes__add", {}))
    with pytest.raises(ValueError):
        Rule.parse("run_shell(unclosed")


def make(mode="default", allow=(), deny=(), answers=None):
    asked = []

    def ask(call):
        asked.append(call)
        return answers.pop(0)

    hook = PermissionHook(mode, TOOLS, allow, deny, ask if answers is not None else None)
    return hook, asked


def test_read_runs_without_asking():
    hook, asked = make(answers=[])
    assert hook.before_tool(ToolCall("1", "read_file", {"path": "a"})) is None and not asked


def test_human_yes_no_always():
    hook, asked = make(answers=["y", "n", "a"])
    assert hook.before_tool(shell("ls")) is None
    assert isinstance(hook.before_tool(shell("ls")), Block)
    assert hook.before_tool(shell("pwd")) is None  # answered "a"
    assert hook.before_tool(shell("whoami")) is None  # no more questions
    assert len(asked) == 3


def test_allow_rule_skips_prompt_and_deny_beats_allow():
    hook, asked = make(allow=["run_shell(git *)"], deny=["run_shell(git push*)"], answers=[])
    assert hook.before_tool(shell("git status")) is None
    blocked = hook.before_tool(shell("git push origin main"))
    assert isinstance(blocked, Block) and "git push*" in blocked.reason
    assert not asked


def test_deny_rule_applies_to_allowed_tools():
    hook, _ = make(deny=["read_file(.env*)"], answers=[])
    assert isinstance(hook.before_tool(ToolCall("1", "read_file", {"path": ".env"})), Block)
    assert hook.before_tool(ToolCall("1", "read_file", {"path": "main.py"})) is None


def test_headless_declines_with_hint():
    hook, _ = make()  # no ask_human
    blocked = hook.before_tool(shell("ls"))
    assert isinstance(blocked, Block) and "--allowed-tools" in blocked.reason


def test_plan_mode_denies_edits():
    hook, _ = make(mode="plan", answers=[])
    blocked = hook.before_tool(ToolCall("1", "write_file", {"path": "a", "content": ""}))
    assert isinstance(blocked, Block) and "plan" in blocked.reason


def test_set_mode_switches_policy():
    hook, _ = make(answers=[])
    hook.set_mode("bypass")
    assert hook.before_tool(shell("rm -rf build")) is None
    assert hook.policy["run_shell"] == "ask"


@pytest.mark.parametrize("mode", ["default", "accept-edits", "plan", "bypass"])
def test_every_mode_passes_trifecta_check(mode, tmp_path):
    hook, _ = make(mode=mode)
    check_trifecta([shell_tool(tmp_path)], [hook])
