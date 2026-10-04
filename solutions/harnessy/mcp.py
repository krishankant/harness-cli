"""MCP (week 9): talk to Model Context Protocol servers over stdio, and turn their tools into
ordinary harnessy Tools.

Targets MCP 2026-07-28 ("modern": no session, every request carries its protocol version in
_meta) and falls back to the initialize handshake of 2025-11-25 and earlier ("legacy") for
servers that don't speak it yet."""

from __future__ import annotations

import itertools
import json
import os
import queue
import re
import subprocess
import threading
from typing import Any, Callable, Iterable

from harnessy.types import Tool, ToolSpec

MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
UNSUPPORTED_PROTOCOL_VERSION = -32022
CLIENT_INFO = {"name": "harnessy", "version": "0.9"}
ALL_TAGS = frozenset({"private_data", "untrusted_input", "external_send"})
ENV_KEYS = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR")
META = "io.modelcontextprotocol/"


class McpError(Exception):
    """A JSON-RPC error from the server, or a protocol situation this client can't handle."""

    def __init__(self, code: int | None, message: str, data: Any = None):
        super().__init__(f"MCP error {code}: {message}" if code is not None else f"MCP error: {message}")
        self.code, self.message, self.data = code, message, data


class McpTimeout(McpError):
    def __init__(self, message: str):
        super().__init__(None, message)


class McpToolError(Exception):
    """An MCP tool ran and reported a failure (isError: true)."""


# --- Given: the stdio transport ----------------------------------------------------------


class StdioTransport:
    """Runs an MCP server as a subprocess; one JSON-RPC message per line on stdin and stdout.

    The server gets a minimal environment (ENV_KEYS plus `env`): your API keys don't reach a
    third-party server unless you pass them on purpose. Its stderr (logs) is discarded."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None):
        full_env = {k: os.environ[k] for k in ENV_KEYS if k in os.environ}
        full_env.update(env or {})
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=full_env, cwd=cwd
        )
        self._pending: dict[Any, queue.Queue] = {}
        self._lock = threading.Lock()  # guards _pending and _closed; never held during I/O
        self._closed = False
        self._broken = False
        self._outbox: queue.Queue = queue.Queue()
        self.notifications: list[dict[str, Any]] = []
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._writer.start()

    def expect(self, request_id: Any) -> queue.Queue:
        """Register interest in the response to request_id (before sending the request)."""
        box: queue.Queue = queue.Queue(maxsize=1)
        with self._lock:
            if self._closed:
                box.put(None)
            else:
                self._pending[request_id] = box
        return box

    def forget(self, request_id: Any) -> None:
        with self._lock:
            self._pending.pop(request_id, None)

    def send(self, message: dict[str, Any]) -> None:
        """Queue one message for the writer thread. Never blocks: a server that stops reading
        can't freeze the caller (the request's own timeout still applies)."""
        if self._broken or self.proc.poll() is not None:
            raise ConnectionError("the MCP server is not running")
        self._outbox.put((json.dumps(message, separators=(",", ":")) + "\n").encode())  # never a raw newline inside

    def _write(self) -> None:
        """The only thread that touches the server's stdin."""
        while True:
            data = self._outbox.get()
            if data is None:
                break
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                self._broken = True
                break
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def _read(self) -> None:
        """Route responses to waiting requests. A bad line is skipped, never fatal."""
        try:
            for raw in self.proc.stdout:
                try:
                    message = json.loads(raw)
                except (ValueError, RecursionError):  # not JSON, not UTF-8, or absurdly deep
                    continue
                request_id = message.get("id") if isinstance(message, dict) else None
                routable = isinstance(request_id, (str, int)) and not isinstance(request_id, bool)
                if routable and ("result" in message or "error" in message):
                    with self._lock:
                        box = self._pending.pop(request_id, None)
                    if box is not None:
                        box.put(message)
                else:
                    self.notifications = (self.notifications + [message])[-100:]
        finally:  # the server closed stdout (or the loop failed): wake everyone still waiting
            with self._lock:
                self._closed = True
                boxes, self._pending = list(self._pending.values()), {}
            for box in boxes:
                box.put(None)
            try:
                self.proc.stdout.close()
            except OSError:
                pass

    def close(self, timeout_s: float = 2.0) -> None:
        """Close stdin (via the writer), wait; then terminate, wait; then kill: the spec's
        shutdown order. A write stuck on a server that stopped reading fails once the server
        is gone. Finally wait for both threads, so no pipe is left open."""
        self._outbox.put(None)
        self._writer.join(timeout=0.5)
        for step in (lambda: None, self.proc.terminate, self.proc.kill):
            if self.proc.poll() is not None:
                break
            step()
            try:
                self.proc.wait(timeout=timeout_s)
                break
            except subprocess.TimeoutExpired:
                continue
        self._writer.join(timeout=timeout_s)
        self._reader.join(timeout=timeout_s)


# --- The client ---------------------------------------------------------------------------


class McpClient:
    def __init__(self, transport: StdioTransport, timeout_s: float = 30.0, probe_timeout_s: float = 10.0):
        self.transport = transport
        self.timeout_s = timeout_s
        self.probe_timeout_s = probe_timeout_s
        self.era: str | None = None  # "modern" or "legacy" once connected
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] = {}
        self.instructions = ""
        self._ids = itertools.count(1)

    # --- Given ---

    @classmethod
    def stdio(cls, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None, **options: Any) -> McpClient:
        return cls(StdioTransport(command, env, cwd), **options)

    def __enter__(self) -> McpClient:
        try:
            self.connect()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.transport.close()

    def _roundtrip(self, message: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Send one request and wait for its response (the raw JSON-RPC message)."""
        box = self.transport.expect(message["id"])
        try:
            self.transport.send(message)
        except ConnectionError:
            self.transport.forget(message["id"])
            raise
        try:
            response = box.get(timeout=timeout)
        except queue.Empty:
            self.transport.forget(message["id"])
            raise McpTimeout(f"no answer to {message['method']} within {timeout:g}s") from None
        if response is None:
            raise ConnectionError("the MCP server closed the connection")
        return response

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.transport.send(message)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    # --- Week 9 exercise ---

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and return its result.

        - The message is {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}.
        - If self.era == "modern", params["_meta"] gets the per-request protocol fields:
          f"{META}protocolVersion": self.protocol_version, f"{META}clientInfo": CLIENT_INFO,
          f"{META}clientCapabilities": {} (keep any _meta the caller passed).
        - Wait with self._roundtrip(message, timeout or self.timeout_s) (given).
        - An "error" response -> raise McpError(error["code"], error["message"], error.get("data")).
        - The result's "resultType" defaults to "complete". Anything else (e.g. "input_required",
          where the server wants user input mid-request) -> raise McpError(None, ...) naming the
          resultType and saying this client can't answer input requests.
        - Return the result dict.
        """
        params = dict(params or {})
        if self.era == "modern":
            params["_meta"] = {
                **params.get("_meta", {}),
                f"{META}protocolVersion": self.protocol_version,
                f"{META}clientInfo": CLIENT_INFO,
                f"{META}clientCapabilities": {},
            }
        message = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        response = self._roundtrip(message, timeout or self.timeout_s)
        if "error" in response:
            err = response["error"] or {}
            raise McpError(err.get("code"), err.get("message", ""), err.get("data"))
        result = response.get("result") or {}
        kind = result.get("resultType", "complete")
        if kind != "complete":
            raise McpError(None, f"the server returned resultType {kind!r}; this client can't answer input requests")
        return result

    def connect(self) -> None:
        """Find out which era the server speaks, then get ready to use it.

        1. Assume modern (self.era = "modern", self.protocol_version = MODERN_VERSION) and send
           "server/discover" with timeout=self.probe_timeout_s.
        2. It answers: modern. MODERN_VERSION must be in result["supportedVersions"] (else raise
           McpError naming them). Store self.server_info = result["_meta"][f"{META}serverInfo"]
           (default {}) and self.instructions = result.get("instructions", "").
        3. McpError with code UNSUPPORTED_PROTOCOL_VERSION: the server is modern but doesn't
           speak our version. Do NOT fall back: raise McpError naming error.data["supported"].
        4. Any other McpError, or McpTimeout: the server is legacy -> self._initialize_legacy().
        (A ConnectionError means the server isn't running: let it propagate.)
        """
        self.era, self.protocol_version = "modern", MODERN_VERSION
        try:
            result = self.request("server/discover", timeout=self.probe_timeout_s)
        except McpTimeout:
            return self._initialize_legacy()
        except McpError as e:
            if e.code == UNSUPPORTED_PROTOCOL_VERSION:
                supported = (e.data or {}).get("supported", [])
                raise McpError(e.code, f"the server supports {supported}; this client speaks {MODERN_VERSION}", e.data) from None
            return self._initialize_legacy()
        supported = result.get("supportedVersions", [])
        if MODERN_VERSION not in supported:
            raise McpError(None, f"the server supports {supported}; this client speaks {MODERN_VERSION}")
        self.server_info = (result.get("_meta") or {}).get(f"{META}serverInfo", {})
        self.instructions = result.get("instructions", "")

    def _initialize_legacy(self) -> None:
        """The legacy handshake (2025-11-25 and earlier).

        Set self.era = "legacy" (so request() stops adding _meta), then request "initialize"
        with {"protocolVersion": LEGACY_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO}.
        The server's result["protocolVersion"] must be in LEGACY_VERSIONS (else McpError naming
        it); store it in self.protocol_version, plus server_info (result["serverInfo"]) and
        instructions. Finally send the "notifications/initialized" notification (self.notify).
        """
        self.era, self.protocol_version = "legacy", None
        result = self.request("initialize", {"protocolVersion": LEGACY_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO})
        version = result.get("protocolVersion")
        if version not in LEGACY_VERSIONS:
            raise McpError(None, f"the server wants protocol {version!r}; this client supports {', '.join(LEGACY_VERSIONS)}")
        self.protocol_version = version
        self.server_info = result.get("serverInfo", {})
        self.instructions = result.get("instructions", "")
        self.notify("notifications/initialized")

    def list_tools(self) -> list[dict[str, Any]]:
        """Every tool the server offers: request "tools/list" (with {"cursor": c} after the
        first page), add result["tools"], and follow result["nextCursor"] until there is none.
        A server that pages forever is a bug: after 100 pages raise McpError mentioning
        "100 pages"."""
        tools: list[dict[str, Any]] = []
        cursor = None
        for _ in range(100):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
        raise McpError(None, "tools/list returned more than 100 pages")


# --- Week 9 exercise ------------------------------------------------------------------------


def content_to_text(result: dict[str, Any]) -> str:
    """Turn a tools/call result into text for the model. One line per content item:
    text -> its text; image/audio -> "[image: <mimeType>]" / "[audio: <mimeType>]";
    resource_link -> "[resource: <uri>]"; resource (embedded) -> its "text" if it has one,
    else "[resource: <uri>]"; anything else -> "[<type> content]". Join with "\\n".
    If there is no content at all but there is "structuredContent", return json.dumps of it.
    Nothing at all -> ""."""
    parts: list[str] = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(item.get("text", ""))
        elif kind in ("image", "audio"):
            parts.append(f"[{kind}: {item.get('mimeType', 'unknown type')}]")
        elif kind == "resource_link":
            parts.append(f"[resource: {item.get('uri', '')}]")
        elif kind == "resource":
            resource = item.get("resource") or {}
            parts.append(resource["text"] if "text" in resource else f"[resource: {resource.get('uri', '')}]")
        else:
            parts.append(f"[{kind} content]")
    if not parts and "structuredContent" in result:
        return json.dumps(result["structuredContent"])
    return "\n".join(parts)


# --- Given ----------------------------------------------------------------------------------


def tool_name(name: str, prefix: str | None = None) -> str:
    """A tool name every provider accepts: only [A-Za-z0-9_-], prefixed "prefix__name" to keep
    two servers' tools apart, at most 64 characters."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    if prefix:
        clean = f"{re.sub(r'[^A-Za-z0-9_-]', '_', prefix)}__{clean}"
    return clean[:64]


def _clean_property(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}  # e.g. `true` ("anything goes") or `false`
    out = dict(schema)
    if "type" in out and not isinstance(out["type"], str):
        out.pop("type")  # e.g. ["string", "null"]: the week 3 validator checks one type only
    if "items" in out:
        out["items"] = _clean_property(out["items"])
    return out


def clean_schema(input_schema: Any) -> dict[str, Any]:
    """An MCP inputSchema reduced to what the week 3 validator can check, so it never crashes
    on a real server's schema: an object with "properties" (each cleaned: a list of types or a
    boolean subschema is dropped, meaning "not checked") and "required" only if it's a list.
    Anything else (enum, descriptions, additionalProperties...) is kept as is."""
    schema = dict(input_schema) if isinstance(input_schema, dict) else {}
    schema["type"] = "object"
    properties = schema.get("properties")
    schema["properties"] = {k: _clean_property(v) for k, v in properties.items()} if isinstance(properties, dict) else {}
    if not isinstance(schema.get("required", []), list):
        schema.pop("required")
    return schema


def _caller(client: McpClient, name: str) -> Callable[..., str]:
    def call(**arguments: Any) -> str:
        result = client.call_tool(name, arguments)
        text = content_to_text(result)
        if result.get("isError"):
            raise McpToolError(text or "the tool reported an error")
        return text

    return call


# --- Week 9 exercise ------------------------------------------------------------------------


def mcp_tools(
    client: McpClient, prefix: str | None = None, tags: Iterable[str] = ALL_TAGS, timeout_s: float | None = None
) -> list[Tool]:
    """One harnessy Tool per MCP tool (client.list_tools()), in the server's order:

    - name: tool_name(mcp["name"], prefix)
    - description: mcp["description"], else mcp["title"], else mcp["name"]
    - parameters: clean_schema(mcp.get("inputSchema")) (given: real servers send schemas the
      week 3 validator can't check, like "type": ["string", "null"]; cleaning keeps it from
      crashing on them)
    - two MCP tools whose cleaned names are the same (e.g. "a.b" and "a_b") -> raise McpError
      naming both and the clash: providers reject duplicate tool names
    - fn: _caller(client, mcp["name"]) (given: calls the tool, joins the content, and raises
      McpToolError when the result has isError, so the model gets an error result)
    - timeout_s as given, max_chars None, tags=frozenset(tags). The default is all three
      lethal-trifecta legs: an MCP server, and the annotations it gives its tools, are
      untrusted unless you say otherwise.
    """
    tools = []
    seen: dict[str, str] = {}
    for info in client.list_tools():
        name = tool_name(info["name"], prefix)
        if name in seen:
            raise McpError(None, f"tools {seen[name]!r} and {info['name']!r} both become {name!r}; rename one or use a prefix")
        seen[name] = info["name"]
        spec = ToolSpec(name, info.get("description") or info.get("title") or info["name"], clean_schema(info.get("inputSchema")))
        tools.append(Tool(spec, _caller(client, info["name"]), timeout_s, None, frozenset(tags)))
    return tools
