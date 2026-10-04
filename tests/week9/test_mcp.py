import sys
import time
from pathlib import Path

import pytest

from harnessy.approvals import ApprovalHook
from harnessy.loop import Agent
from harnessy.mcp import ALL_TAGS, McpClient, McpError, McpTimeout, content_to_text, mcp_tools, tool_name
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.safety import TrifectaError
from harnessy.tools.registry import ToolRegistry
from harnessy.types import ToolCall

SERVER = [sys.executable, str(Path(__file__).with_name("fake_server.py"))]
ALL_NAMES = ["echo", "fail", "files.read", "mixed", "sleep", "ask", "env", "maybe"]


def client(mode: str, **options) -> McpClient:
    return McpClient.stdio([*SERVER, mode], **options)


def test_a_modern_server():
    with client("modern") as c:
        assert (c.era, c.protocol_version) == ("modern", "2026-07-28")
        assert (c.server_info.get("name"), c.instructions) == ("fake", "Fake server.")
        assert content_to_text(c.call_tool("echo", {"text": "hi"})) == "hi (via 2026-07-28)"


def test_a_legacy_server_falls_back_to_initialize():
    with client("legacy") as c:
        assert (c.era, c.protocol_version, c.server_info.get("name")) == ("legacy", "2025-11-25", "fake-legacy")
        assert c.instructions == "Legacy fake."
        assert content_to_text(c.call_tool("echo", {"text": "hi"})) == "hi (via legacy)"


def test_a_silent_legacy_server_falls_back_after_the_probe_timeout():
    start = time.monotonic()
    with client("silent-legacy", probe_timeout_s=0.3) as c:
        assert c.era == "legacy"
        assert content_to_text(c.call_tool("echo", {"text": "hi"})) == "hi (via legacy)"
    assert time.monotonic() - start < 5


def test_a_dual_era_server_is_used_as_modern():
    with client("dual") as c:
        assert c.era == "modern"
        assert content_to_text(c.call_tool("echo", {"text": "hi"})) == "hi (via 2026-07-28)"


def test_an_unsupported_modern_version_is_an_error_not_a_fallback():
    c = client("future")
    try:
        with pytest.raises(McpError, match="2027-01-01"):
            c.connect()
        assert c.era != "legacy"
    finally:
        c.close()


def test_list_tools_follows_every_page():
    with client("modern") as c:
        assert [t["name"] for t in c.list_tools()] == ALL_NAMES


def test_endless_paging_is_capped():
    with client("endless") as c:
        with pytest.raises(McpError, match="100 pages"):
            c.list_tools()


def test_protocol_errors_raise_mcp_error():
    with client("modern") as c:
        with pytest.raises(McpError) as err:
            c.call_tool("nope", {})
        assert err.value.code == -32602 and "Unknown tool" in err.value.message


def test_input_required_results_are_refused():
    with client("modern") as c:
        with pytest.raises(McpError, match="input_required"):
            c.call_tool("ask", {})


def test_a_request_times_out():
    with client("modern", timeout_s=0.3) as c:
        with pytest.raises(McpTimeout):
            c.call_tool("sleep", {})


def test_a_crashed_server_is_a_connection_error():
    with client("crash") as c:
        with pytest.raises(ConnectionError):
            c.call_tool("echo", {"text": "x"})


def test_close_stops_the_server():
    c = client("modern")
    c.connect()
    c.close()
    assert c.transport.proc.poll() is not None


def test_the_server_gets_a_minimal_environment(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    with McpClient.stdio([*SERVER, "modern"], env={"EXTRA": "1"}) as c:
        names = content_to_text(c.call_tool("env", {})).split(",")
    assert "SECRET_TOKEN" not in names and "EXTRA" in names and "PATH" in names


def test_content_to_text():
    result = {"content": [
        {"type": "text", "text": "hello"},
        {"type": "image", "data": "AAAA", "mimeType": "image/png"},
        {"type": "audio", "data": "AAAA", "mimeType": "audio/wav"},
        {"type": "resource_link", "uri": "file:///a.txt", "name": "a.txt"},
        {"type": "resource", "resource": {"uri": "file:///b.txt", "text": "inline b"}},
        {"type": "resource", "resource": {"uri": "file:///c.bin", "blob": "AAAA"}},
        {"type": "weird"},
    ]}
    assert content_to_text(result) == (
        "hello\n[image: image/png]\n[audio: audio/wav]\n[resource: file:///a.txt]\ninline b\n[resource: file:///c.bin]\n[weird content]"
    )
    assert content_to_text({"content": [], "structuredContent": {"a": 1}}) == '{"a": 1}'
    assert content_to_text({}) == ""


def test_tool_name_is_given():
    assert tool_name("files.read") == "files_read"
    assert tool_name("files.read", "my server") == "my_server__files_read"
    assert len(tool_name("x" * 100)) == 64


def test_mcp_tools_become_harnessy_tools():
    with client("modern") as c:
        tools = mcp_tools(c, prefix="fake")
        assert [t.name for t in tools] == [f"fake__{tool_name(n)}" for n in ALL_NAMES]
        by_name = {t.name: t for t in tools}
        assert by_name["fake__echo"].spec.parameters["required"] == ["text"]
        assert by_name["fake__files_read"].spec.description == "Read a file"
        assert by_name["fake__sleep"].spec.parameters == {"type": "object", "properties": {}}
        assert all(t.tags == ALL_TAGS for t in tools)
        registry = ToolRegistry(tools)
        assert registry.call(ToolCall("c1", "fake__echo", {"text": "yo"})).content == "yo (via 2026-07-28)"
        bad = registry.call(ToolCall("c2", "fake__echo", {}))
        assert bad.is_error and "missing required parameter 'text'" in bad.content
        failed = registry.call(ToolCall("c3", "fake__fail", {}))
        assert failed.is_error and "disk on fire" in failed.content
        assert mcp_tools(c, tags=())[0].tags == frozenset()


def test_an_agent_uses_mcp_tools_behind_an_approval_hook():
    with client("modern") as c:
        tools = mcp_tools(c, prefix="fake")
        with pytest.raises(TrifectaError):
            Agent(ScriptedModel([]), tools=tools)
        model = ScriptedModel([tool_reply(ToolCall("t1", "fake__echo", {"text": "hello"})), text_reply("done")])
        agent = Agent(model, tools=tools, hooks=[ApprovalHook({}, approver=lambda call: True, default="ask")])
        r = agent.run("echo hello")
        assert r.messages[2].tool_results[0].content == "hello (via 2026-07-28)" and r.stop_reason == "end_turn"


def test_close_releases_both_pipes_even_after_a_crash():
    for mode, crash in (("modern", False), ("crash", True)):
        with client(mode) as c:
            if crash:
                with pytest.raises(ConnectionError):
                    c.call_tool("echo", {"text": "x"})
        assert c.transport.proc.stdin.closed and c.transport.proc.stdout.closed, mode


def test_bad_lines_from_the_server_do_not_kill_the_client():
    with client("garbage") as c:
        assert c.era == "modern" and c.transport._reader.is_alive()
        assert content_to_text(c.call_tool("echo", {"text": "still here"})) == "still here (via 2026-07-28)"


def test_a_big_request_to_a_deaf_server_times_out_and_close_still_works():
    c = client("deaf", timeout_s=0.5)
    c.connect()
    start = time.monotonic()
    with pytest.raises(McpTimeout):
        c.call_tool("echo", {"text": "x" * 300_000})  # bigger than the pipe buffer
    with pytest.raises(McpTimeout):
        c.call_tool("echo", {"text": "small"})  # not stuck behind the big write
    c.close()
    assert c.transport.proc.poll() is not None and time.monotonic() - start < 10


def test_a_slow_starting_modern_server_is_not_mistaken_for_legacy():
    with client("slowstart") as c:  # the default probe timeout must cover start-up
        assert c.era == "modern"


def test_awkward_schemas_do_not_crash_the_registry():
    with client("modern") as c:
        maybe = next(t for t in mcp_tools(c) if t.name == "maybe")
        props = maybe.spec.parameters["properties"]
        assert props["note"] == {} and props["anything"] == {} and props["tags"] == {"type": "array", "items": {}}
        registry = ToolRegistry([maybe])
        assert registry.call(ToolCall("c1", "maybe", {"note": None, "anything": 3, "tags": ["a", 1]})).content == "note=None"
        assert registry.call(ToolCall("c2", "maybe", {"note": "hi"})).content == "note='hi'"


class ListingOnly:
    """Just enough of a client for mcp_tools: it only lists tools."""

    def __init__(self, names):
        self.names = names

    def list_tools(self):
        return [{"name": n, "inputSchema": {"type": "object"}} for n in self.names]


def test_tool_names_that_collide_after_cleaning_are_an_error():
    mcp_tools(ListingOnly(["a.b"]))  # fails plainly while mcp_tools is a stub
    with pytest.raises(McpError, match="a_b"):
        mcp_tools(ListingOnly(["a.b", "a_b"]))
