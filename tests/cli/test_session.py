import os
import time

import pytest

from harness_cli import session as sessions
from harness_cli.session import Session, SessionError
from harnessy.types import Message, ProviderRaw, ToolCall, ToolResult, Usage


def sample_messages():
    return [
        Message("user", text="fix it"),
        Message(
            "assistant",
            text="Looking.",
            tool_calls=(ToolCall("t1", "read_file", {"path": "a.py"}),),
            raw=ProviderRaw("anthropic", [{"type": "text", "text": "Looking."}, {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}}]),
        ),
        Message("user", tool_results=(ToolResult("t1", "1\tx = 1", False), ToolResult("t2", "boom", True))),
        Message("assistant", text="Done."),
    ]


def test_round_trip(workspace):
    s = Session.new(workspace, "anthropic", "claude-opus-5")
    s.messages = sample_messages()
    s.usage, s.cost_usd = Usage(100, 20), 0.0123
    s.save()
    loaded = sessions.load(workspace, s.id)
    assert loaded.messages == s.messages
    assert loaded.usage == Usage(100, 20) and loaded.cost_usd == pytest.approx(0.0123)
    assert (loaded.provider, loaded.model) == ("anthropic", "claude-opus-5")


def test_latest_and_prefix(workspace):
    a = Session.new(workspace, "anthropic", None)
    a.messages = [Message("user", text="first")]
    a.save()
    b = Session.new(workspace, "anthropic", None)
    b.messages = [Message("user", text="second")]
    b.save()
    os.utime(a.path, (time.time() - 100, time.time() - 100))
    assert sessions.latest(workspace).id == b.id
    assert sessions.load(workspace, b.id[-4:]).id == b.id  # the random suffix is enough


def test_ambiguous_and_missing(workspace):
    for _ in range(2):
        s = Session.new(workspace, "anthropic", None)
        s.messages = [Message("user", text="x")]
        s.save()
    with pytest.raises(SessionError, match="matches 2"):
        sessions.load(workspace, "")
    with pytest.raises(SessionError, match="no session"):
        sessions.load(workspace, "zzzz")


def test_empty_sessions_are_not_saved(workspace):
    s = Session.new(workspace, "anthropic", None)
    s.save()
    assert sessions.latest(workspace) is None


def test_load_skips_corrupt_line(workspace):
    s = Session.new(workspace, "anthropic", None)
    s.messages = sample_messages()
    s.save()
    lines = s.path.read_text().splitlines()
    lines.insert(2, '{"type": "message", "role": "user", "te')  # killed mid-write
    s.path.write_text("\n".join(lines) + "\n")
    loaded = sessions.load(workspace, s.id)
    assert loaded.messages == s.messages
    assert loaded.skipped_lines == 1


def test_list_is_per_workspace(workspace, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    s = Session.new(workspace, "anthropic", None)
    s.messages = [Message("user", text="hello there")]
    s.save()
    infos = sessions.list_sessions(workspace)
    assert [i.id for i in infos] == [s.id] and infos[0].title == "hello there"
    assert sessions.list_sessions(other) == []
