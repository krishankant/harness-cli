"""A tiny MCP server for the week 9 tests, speaking whichever era a test asks for.

    python fake_server.py MODE

modern         2026-07-28 only (per-request _meta, resultType on every result)
legacy         initialize handshake only; answers server/discover with -32601
dual           both: server/discover works, and so does initialize
silent-legacy  legacy, but never answers server/discover
future         modern, but only supports 2027-01-01 (answers -32022)
endless        modern, and tools/list pages never end
crash          modern, and exits on the first tools/call
garbage        modern, but first writes lines a client must survive (bad bytes, deep JSON, odd ids)
deaf           modern, but stops reading stdin after server/discover
slowstart      modern, but takes 3.5 s to start
"""

import json
import os
import sys
import time

MODE = sys.argv[1]
MODERN = "2026-07-28"
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"
TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
    },
    {"name": "fail", "description": "Always fails.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "files.read", "title": "Read a file", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "mixed", "description": "Returns every content type.", "inputSchema": {"type": "object"}},
    {"name": "sleep", "description": "Never answers."},
    {"name": "ask", "description": "Needs user input.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "env", "description": "Lists the environment variable names it can see.", "inputSchema": {"type": "object"}},
    {
        "name": "maybe",
        "description": "Has the awkward schemas real servers send.",
        "inputSchema": {"type": "object", "properties": {"note": {"type": ["string", "null"]}, "anything": True, "tags": {"type": "array", "items": {"type": ["string", "number"]}}}},
    },
]
if MODE == "slowstart":
    time.sleep(3.5)
answers_initialize = MODE in ("legacy", "silent-legacy", "dual")
answers_discover = MODE not in ("legacy", "silent-legacy")
initialized = False


def raw(data):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def reply(mid, result):
    if not initialized:  # modern results carry resultType; legacy ones don't
        result = {"resultType": "complete", **result}
    send({"jsonrpc": "2.0", "id": mid, "result": result})


def error(mid, code, message, data=None):
    body = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    send({"jsonrpc": "2.0", "id": mid, "error": body})


def call_tool(mid, params, version):
    name, args = params.get("name"), params.get("arguments") or {}
    if name == "echo":
        return reply(mid, {"content": [{"type": "text", "text": f"{args.get('text')} (via {version})"}]})
    if name == "fail":
        return reply(mid, {"content": [{"type": "text", "text": "disk on fire"}], "isError": True})
    if name == "files.read":
        return reply(mid, {"content": [{"type": "text", "text": f"contents of {args.get('path')}"}]})
    if name == "mixed":
        return reply(mid, {"content": [
            {"type": "text", "text": "hello"},
            {"type": "image", "data": "AAAA", "mimeType": "image/png"},
            {"type": "resource_link", "uri": "file:///a.txt", "name": "a.txt"},
            {"type": "resource", "resource": {"uri": "file:///b.txt", "text": "inline b"}},
        ]})
    if name == "sleep":
        return None  # never answers
    if name == "ask":
        return send({"jsonrpc": "2.0", "id": mid, "result": {
            "resultType": "input_required",
            "inputRequests": {"q": {"method": "elicitation/create", "params": {"mode": "form", "message": "Name?"}}},
        }})
    if name == "maybe":
        return reply(mid, {"content": [{"type": "text", "text": f"note={args.get('note')!r}"}]})
    if name == "env":
        return reply(mid, {"content": [{"type": "text", "text": ",".join(sorted(os.environ))}]})
    return error(mid, -32602, f"Unknown tool: {name}")


for line in sys.stdin:
    msg = json.loads(line)
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    meta = params.get("_meta") or {}
    if mid is None:
        if method == "notifications/initialized":
            initialized = True
        continue
    if method == "server/discover":
        if MODE == "garbage":
            raw(b"\xff\xfe not utf-8\n")
            raw(("[" * 100_000 + "]" * 100_000 + "\n").encode())
            raw(b'{"jsonrpc": "2.0", "id": [1], "result": {}}\n')
            raw(b'{"jsonrpc": "2.0", "id": true, "result": {}}\n')
        if MODE == "silent-legacy":
            continue
        if not answers_discover:
            error(mid, -32601, "Method not found")
        elif MODE == "future":
            error(mid, -32022, "Unsupported protocol version", {"supported": ["2027-01-01"], "requested": meta.get(VERSION_KEY)})
        else:
            reply(mid, {
                "supportedVersions": [MODERN],
                "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "fake", "version": "1"}},
                "instructions": "Fake server.",
            })
        if MODE == "deaf":
            time.sleep(60)  # stops reading stdin: the client's big writes will block
        continue
    if method == "initialize":
        if not answers_initialize:
            error(mid, -32601, "Method not found")
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-legacy", "version": "1"},
                "instructions": "Legacy fake.",
            }})
        continue
    if initialized:
        version = "legacy"
    elif meta.get(VERSION_KEY) and CAPS_KEY in meta:
        version = meta[VERSION_KEY]
    else:
        error(mid, -32602, "Missing _meta protocol fields, and no initialize handshake")
        continue
    if method == "tools/list":
        if MODE == "endless":
            reply(mid, {"tools": TOOLS[:2], "nextCursor": "again"})
            continue
        start = int(params.get("cursor") or 0)
        page = {"tools": TOOLS[start : start + 2]}
        if start + 2 < len(TOOLS):
            page["nextCursor"] = str(start + 2)
        reply(mid, page)
    elif method == "tools/call":
        if MODE == "crash":
            sys.exit(1)
        call_tool(mid, params, version)
    else:
        error(mid, -32601, f"Method not found: {method}")
