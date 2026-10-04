import pytest

from harnessy.approvals import ApprovalHook, terminal_approver
from harnessy.hooks import Block
from harnessy.types import ToolCall

CALL = ToolCall("c1", "write_file", {"path": "a.txt", "content": "b"})


def test_allow_is_the_default():
    assert ApprovalHook({}).before_tool(CALL) is None
    assert ApprovalHook({"write_file": "allow"}).before_tool(CALL) is None


def test_deny():
    assert ApprovalHook({"write_file": "deny"}).before_tool(CALL) == Block("'write_file' is not allowed by policy.")


def test_ask_without_an_approver():
    assert ApprovalHook({"write_file": "ask"}).before_tool(CALL) == Block("'write_file' needs approval, and no approver is set.")


def test_ask_and_approved():
    seen = []
    hook = ApprovalHook({"write_file": "ask"}, approver=lambda call: seen.append(call) or True)
    assert hook.before_tool(CALL) is None and seen == [CALL]


def test_ask_and_declined():
    hook = ApprovalHook({"write_file": "ask"}, approver=lambda call: False)
    assert hook.before_tool(CALL) == Block("The user declined 'write_file'. Ask what they want instead, or try another way.")


def test_the_default_covers_unlisted_tools():
    assert ApprovalHook({}, default="deny").before_tool(CALL) == Block("'write_file' is not allowed by policy.")


def test_a_bad_policy_value_is_rejected():
    with pytest.raises(ValueError, match="maybe"):
        ApprovalHook({"write_file": "maybe"})


def test_terminal_approver_is_given():
    quiet = lambda *args: None  # noqa: E731
    assert terminal_approver(CALL, input_fn=lambda prompt: "y", printer=quiet) is True
    assert terminal_approver(CALL, input_fn=lambda prompt: "YES ", printer=quiet) is True
    assert terminal_approver(CALL, input_fn=lambda prompt: "", printer=quiet) is False
