"""An example MCP server (week 9): a tiny notes store that speaks both MCP eras.

An MCP client runs it over stdio:  python scripts/mcp_notes_server.py notes.json
It reads one JSON-RPC message per line on stdin and writes one per line on stdout.
Standard library only, so you can read the other side of the protocol in one file."""

import json
import sys
from pathlib import Path

STORE = Path(sys.argv[1] if len(sys.argv) > 1 else "notes.json")
MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26")
META = "io.modelcontextprotocol/"
INFO = {"name": "harnessy-notes", "version": "1.0"}
INSTRUCTIONS = "A small notes store. Titles are unique: saving a note with an existing title replaces it."
TOOLS = [
    {
        "name": "add_note",
        "description": "Save a note with a title and text. Saving an existing title replaces that note.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "A short title."}, "text": {"type": "string", "description": "The note itself."}},
            "required": ["title", "text"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "list_notes",
        "description": "List the titles of every saved note.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "search_notes",
        "description": "Find notes whose title or text contains any of the given words (case-insensitive).",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Words to look for."}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
]
legacy_session = False  # set by initialize: this process then speaks the legacy protocol


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def save(notes):
    STORE.write_text(json.dumps(notes, indent=2))


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def result(mid, body):
    if not legacy_session:
        body = {"resultType": "complete", **body, "_meta": {f"{META}serverInfo": INFO}}
    send({"jsonrpc": "2.0", "id": mid, "result": body})


def error(mid, code, message, data=None):
    body = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    send({"jsonrpc": "2.0", "id": mid, "error": body})


def text(message, is_error=False):
    return {"content": [{"type": "text", "text": message}], "isError": is_error}


def call_tool(name, args):
    notes = load()
    if name == "add_note":
        notes[args["title"]] = args["text"]
        save(notes)
        count = len(notes)
        return text(f"Saved '{args['title']}'. {count} note{'' if count == 1 else 's'} in the store.")
    if name == "list_notes":
        return text("\n".join(f"- {title}" for title in sorted(notes)) or "No notes yet.")
    if name == "search_notes":
        words = args["query"].lower().split()
        hits = [f"- {title}: {body}" for title, body in sorted(notes.items()) if any(w in f"{title} {body}".lower() for w in words)]
        return text("\n".join(hits) or f"No notes match '{args['query']}'.")
    return None


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        continue  # notifications (e.g. notifications/initialized) need no answer
    meta = params.get("_meta") or {}
    try:
        if method == "server/discover":
            requested = meta.get(f"{META}protocolVersion")
            if requested != MODERN:
                error(mid, -32022, "Unsupported protocol version", {"supported": [MODERN], "requested": requested})
            else:
                result(mid, {"supportedVersions": [MODERN], "capabilities": {"tools": {}}, "instructions": INSTRUCTIONS})
        elif method == "initialize":
            legacy_session = True
            asked = params.get("protocolVersion")
            result(mid, {"protocolVersion": asked if asked in LEGACY else LEGACY[0], "capabilities": {"tools": {}},
                         "serverInfo": INFO, "instructions": INSTRUCTIONS})
        elif not legacy_session and meta.get(f"{META}protocolVersion") != MODERN:
            error(mid, -32602, f"Missing or unsupported {META}protocolVersion in _meta")
        elif method == "tools/list":
            result(mid, {"tools": TOOLS})
        elif method == "tools/call":
            out = call_tool(params.get("name"), params.get("arguments") or {})
            if out is None:
                error(mid, -32602, f"Unknown tool: {params.get('name')}")
            else:
                result(mid, out)
        else:
            error(mid, -32601, f"Method not found: {method}")
    except Exception as e:  # a bug in a tool is a tool error, not a dead server
        result(mid, text(f"{type(e).__name__}: {e}", is_error=True))
