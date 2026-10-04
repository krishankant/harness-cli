"""Sessions: a conversation saved as JSON lines, so `harness -c` and `/resume` can pick it up.

~/.harness/sessions/<project-key>/<id>.jsonl
  line 1: {"type": "session", "id", "workspace", "created", "provider", "model"}
  then:   {"type": "message", ...one harnessy Message...}
  last:   {"type": "usage", "input_tokens", "output_tokens", "cost_usd"}

save() writes a temp file and renames it over the old one, so a crash never leaves half a
file; load() still skips any line it can't read rather than losing the whole session."""

from __future__ import annotations

import datetime
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_cli.config import harness_home
from harnessy.tracer import to_jsonable
from harnessy.types import Message, ProviderRaw, ToolCall, ToolResult, Usage


class SessionError(ValueError):
    pass


def project_dir(workspace: Path) -> Path:
    key = str(Path(workspace).resolve()).replace(os.sep, "-").strip("-") or "root"
    return harness_home() / "sessions" / key


def message_to_json(m: Message) -> dict[str, Any]:
    return {"type": "message", **to_jsonable(m)}


def message_from_json(d: dict[str, Any]) -> Message:
    raw = d.get("raw")
    return Message(
        role=d["role"],
        text=d.get("text", ""),
        tool_calls=tuple(ToolCall(c["id"], c["name"], c.get("arguments") or {}) for c in d.get("tool_calls") or ()),
        tool_results=tuple(ToolResult(r["tool_call_id"], r["content"], bool(r.get("is_error"))) for r in d.get("tool_results") or ()),
        raw=ProviderRaw(raw["provider"], raw["content"]) if raw else None,
    )


def new_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


@dataclass
class Session:
    id: str
    workspace: Path
    provider: str
    model: str | None
    created: str = ""
    messages: list[Message] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    skipped_lines: int = 0

    @classmethod
    def new(cls, workspace: Path, provider: str, model: str | None) -> Session:
        return cls(new_id(), Path(workspace).resolve(), provider, model, created=datetime.datetime.now().isoformat(timespec="seconds"))

    @property
    def path(self) -> Path:
        return project_dir(self.workspace) / f"{self.id}.jsonl"

    @property
    def title(self) -> str:
        first = next((m.text for m in self.messages if m.role == "user" and m.text), "")
        return " ".join(first.split())[:60]

    def save(self) -> None:
        """Write the whole session. A session with no messages yet is not written."""
        if not self.messages:
            return
        header = {"type": "session", "id": self.id, "workspace": str(self.workspace), "created": self.created, "provider": self.provider, "model": self.model}
        usage = {"type": "usage", "input_tokens": self.usage.input_tokens, "output_tokens": self.usage.output_tokens, "cost_usd": self.cost_usd}
        lines = [header, *(message_to_json(m) for m in self.messages), usage]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(line) + "\n" for line in lines))
        os.replace(tmp, self.path)


def read(path: Path) -> Session:
    session: Session | None = None
    messages: list[Message] = []
    usage, cost, skipped = Usage(), 0.0, 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            kind = d.get("type")
            if kind == "session":
                session = Session(d["id"], Path(d["workspace"]), d.get("provider", "anthropic"), d.get("model"), d.get("created", ""))
            elif kind == "message":
                messages.append(message_from_json(d))
            elif kind == "usage":
                usage, cost = Usage(d.get("input_tokens", 0), d.get("output_tokens", 0)), float(d.get("cost_usd", 0.0))
        except (ValueError, KeyError, TypeError):
            skipped += 1
    if session is None:
        raise SessionError(f"{path}: not a session file (no header line)")
    session.messages, session.usage, session.cost_usd, session.skipped_lines = messages, usage, cost, skipped
    return session


def _files(workspace: Path) -> list[Path]:
    folder = project_dir(workspace)
    files = list(folder.glob("*.jsonl")) if folder.is_dir() else []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def load(workspace: Path, id_or_prefix: str) -> Session:
    hits = [p for p in _files(workspace) if p.stem.startswith(id_or_prefix) or p.stem.endswith(id_or_prefix)] if id_or_prefix else _files(workspace)
    exact = [p for p in hits if p.stem == id_or_prefix]
    if exact:
        return read(exact[0])
    if not hits:
        raise SessionError(f"no session '{id_or_prefix}' for {workspace}; see /sessions")
    if len(hits) > 1:
        raise SessionError(f"'{id_or_prefix}' matches {len(hits)} sessions; use more of the id")
    return read(hits[0])


def latest(workspace: Path) -> Session | None:
    files = _files(workspace)
    return read(files[0]) if files else None


@dataclass(frozen=True)
class SessionInfo:
    id: str
    modified: datetime.datetime
    title: str
    turns: int


def list_sessions(workspace: Path, limit: int = 20) -> list[SessionInfo]:
    out = []
    for path in _files(workspace)[:limit]:
        try:
            s = read(path)
        except SessionError:
            continue
        turns = sum(1 for m in s.messages if m.role == "user" and m.text)
        out.append(SessionInfo(s.id, datetime.datetime.fromtimestamp(path.stat().st_mtime), s.title, turns))
    return out
