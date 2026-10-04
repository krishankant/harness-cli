import json

import pytest

from harnessy.approvals import ApprovalHook
from harnessy.safety import TrifectaError, check_trifecta
from harnessy.tools.files import file_tools
from harnessy.tools.outbox import outbox_tool
from harnessy.tools.web import http_get


@pytest.fixture
def tools(tmp_path):
    return [*file_tools(tmp_path), http_get, outbox_tool(tmp_path / "outbox.jsonl")]


def test_two_legs_are_fine(tmp_path):
    check_trifecta(file_tools(tmp_path), [])
    check_trifecta([*file_tools(tmp_path), outbox_tool(tmp_path / "o.jsonl")], [])


def test_all_three_legs_without_approval_are_refused(tools):
    check_trifecta(tools, [ApprovalHook({"http_get": "ask", "send_email": "deny"})])  # fails plainly while a stub
    with pytest.raises(TrifectaError, match="http_get, send_email"):
        check_trifecta(tools, [])


def test_every_sending_tool_must_be_guarded(tools):
    with pytest.raises(TrifectaError, match="send_email") as err:
        check_trifecta(tools, [ApprovalHook({"http_get": "ask"})])
    assert "http_get" not in str(err.value).split("without approval:")[1]


def test_allow_does_not_count_but_a_strict_default_does(tools):
    with pytest.raises(TrifectaError):
        check_trifecta(tools, [ApprovalHook({"http_get": "allow", "send_email": "ask"})])
    check_trifecta(tools, [ApprovalHook({}, default="ask")])


def test_outbox_is_given(tmp_path):
    send = outbox_tool(tmp_path / "out" / "outbox.jsonl")
    assert send.tags == frozenset({"external_send"})
    assert send.fn(to="a@example.com", subject="hi", body="text") == "Sent to a@example.com."
    assert json.loads((tmp_path / "out" / "outbox.jsonl").read_text()) == {"to": "a@example.com", "subject": "hi", "body": "text"}
