"""harness -p: one turn, no human, output for scripts.

Permissions are fixed before the run: anything that would ask is declined (and the model is told
how the user could allow it), exactly like `claude -p` or `codex exec`."""

from __future__ import annotations

import json
from typing import Any, TextIO

from harness_cli.app import App
from harness_cli.engine import Done, TextDelta, ToolEnd, ToolStart
from harnessy.tracer import to_jsonable

FORMATS = ("text", "json", "stream-json")


def _event_json(event: Any, session_id: str) -> dict[str, Any] | None:
    if isinstance(event, TextDelta):
        return {"type": "text", "text": event.text}
    if isinstance(event, ToolStart):
        return {"type": "tool_start", "id": event.call.id, "name": event.call.name, "arguments": to_jsonable(event.call.arguments)}
    if isinstance(event, ToolEnd):
        r = event.result
        return {"type": "tool_end", "id": event.call.id, "name": event.call.name, "is_error": r.is_error, "content": r.content}
    if isinstance(event, Done):
        return {"type": "done", **summary(event.result, session_id)}
    return None


def summary(result: Any, session_id: str) -> dict[str, Any]:
    return {
        "result": result.final_text,
        "stop_reason": result.stop_reason,
        "error": result.error,
        "session_id": session_id,
        "steps": len(result.steps),
        "usage": {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens},
        "cost_usd": round(result.cost_usd, 6),
    }


def run_headless(app: App, prompt: str, output_format: str, out: TextIO, err: TextIO) -> int:
    def on_event(event: Any) -> None:
        if output_format == "stream-json":
            data = _event_json(event, app.session.id)
            if data is not None:
                out.write(json.dumps(data) + "\n")
                out.flush()
        elif isinstance(event, ToolEnd) and event.result.is_error:
            err.write(f"[{event.call.name}] {event.result.content.splitlines()[0] if event.result.content else 'error'}\n")

    try:
        result = app.run_turn(prompt, on_event=on_event)
    finally:
        app.close()
    if output_format == "text":
        out.write(result.final_text.rstrip() + "\n" if result.final_text else "")
    elif output_format == "json":
        out.write(json.dumps(summary(result, app.session.id), indent=2) + "\n")
    if result.stop_reason != "end_turn":
        err.write(f"harness: stopped with {result.stop_reason}" + (f": {result.error}" if result.error else "") + "\n")
        return 1
    return 0
