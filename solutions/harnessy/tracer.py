"""Tracing (week 5): one JSON line per event, so you can read what a run did afterwards.

In week 6 the loop stops calling the tracer directly: TraceHook (bottom of this file)
emits the same events from the hook points."""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from harnessy.hooks import Hook

# --- Given -----------------------------------------------------------------------------


def to_jsonable(obj: Any) -> Any:
    """Dataclasses become dicts (recursively), tuples become lists, anything else JSON
    can't hold becomes str()."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def load_trace(path: str | Path, run_id: str | None = None) -> list[dict[str, Any]]:
    """The events of one run: run_id's, or the last run in the file."""
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not events:
        return []
    wanted = run_id or events[-1]["run_id"]
    return [e for e in events if e["run_id"] == wanted]


def _short(text: Any, limit: int = 60) -> str:
    text = str(text).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


# --- Week 5 exercise -------------------------------------------------------------------


class Tracer:
    def __init__(self, path: str | Path, clock: Callable[[], float] = time.monotonic):
        self.path = Path(path)
        self.clock = clock
        self.run_id: str | None = None
        self._t0 = 0.0
        self._seq = 0

    def event(self, kind: str, **data: Any) -> None:
        """Append one event to the file as a JSON line.

        - Call self.clock() once per event.
        - kind == "run_start" starts a new run: run_id = uuid.uuid4().hex[:8], t0 = now, seq = 0.
        - Any other kind before the first run_start: raise RuntimeError (mention "run_start").
        - The line is {"run_id", "seq", "t": round(now - t0, 3), "kind", **to_jsonable(data)};
          then seq goes up by one.
        - Create the file's parent folders if needed; open the file in append mode.
        """
        now = self.clock()
        if kind == "run_start":
            self.run_id, self._t0, self._seq = uuid.uuid4().hex[:8], now, 0
        elif self.run_id is None:
            raise RuntimeError("Tracer: the first event of a run must be 'run_start'")
        record = {"run_id": self.run_id, "seq": self._seq, "t": round(now - self._t0, 3), "kind": kind, **to_jsonable(data)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        self._seq += 1


def format_timeline(events: list[dict[str, Any]]) -> str:
    """One run as readable lines. dt is this event's t minus the previous event's t (0 for
    the first). Use _short() (60 characters) for text and content.

    run_start   -> "run {run_id}  model={model}  tools={names joined ', ' or '-'}"
                   and a second line "task: {_short(task, 100)}"
    model_call  -> "[{t:7.2f}s +{dt:5.2f}s] step {step} model {stop_reason} in={input_tokens} out={output_tokens} {what}"
                   where what = _short of the calls as name(json.dumps(arguments)) joined ", ",
                   or of repr(text) if there are no calls
    tool_result -> "[{t:7.2f}s +{dt:5.2f}s]   {name} -> {'ERROR ' if is_error}{_short(content)}"
    stop        -> "[{t:7.2f}s] stop {stop_reason} steps={steps} tokens={input + output}"
                   plus " error={error}" when there is one
    other kinds -> "[{t:7.2f}s] {kind} {_short(json.dumps(the other keys))}"
    """
    lines: list[str] = []
    prev = None
    for e in events:
        t = e.get("t", 0.0)
        dt = 0.0 if prev is None else t - prev
        prev = t
        kind = e["kind"]
        if kind == "run_start":
            lines.append(f"run {e['run_id']}  model={e.get('model')}  tools={', '.join(e.get('tools') or []) or '-'}")
            lines.append(f"task: {_short(e.get('task', ''), 100)}")
        elif kind == "model_call":
            calls = ", ".join(f"{c['name']}({json.dumps(c['arguments'])})" for c in e.get("tool_calls") or [])
            what = _short(calls or repr(e.get("text", "")))
            lines.append(
                f"[{t:7.2f}s +{dt:5.2f}s] step {e['step']} model {e['stop_reason']} "
                f"in={e['input_tokens']} out={e['output_tokens']} {what}"
            )
        elif kind == "tool_result":
            flag = "ERROR " if e.get("is_error") else ""
            lines.append(f"[{t:7.2f}s +{dt:5.2f}s]   {e['name']} -> {flag}{_short(e.get('content', ''))}")
        elif kind == "stop":
            total = e.get("input_tokens", 0) + e.get("output_tokens", 0)
            error = f" error={e['error']}" if e.get("error") else ""
            lines.append(f"[{t:7.2f}s] stop {e['stop_reason']} steps={e['steps']} tokens={total}{error}")
        else:
            rest = {k: v for k, v in e.items() if k not in ("run_id", "seq", "t", "kind")}
            lines.append(f"[{t:7.2f}s] {kind} {_short(json.dumps(rest))}")
    return "\n".join(lines)


# --- Given (week 6) --------------------------------------------------------------------


class TraceHook(Hook):
    """Week 6: the week 5 events, emitted from hook points instead of from inside the loop."""

    def __init__(self, tracer: Tracer):
        self.tracer = tracer
        self._calls = 0

    def on_start(self, agent: Any, task: str) -> None:
        self._calls = 0
        self.tracer.event("run_start", task=task, model=agent.model.name, system=agent.system, tools=[t.name for t in agent.tools])

    def after_model(self, response: Any) -> None:
        self.tracer.event(
            "model_call", step=self._calls, stop_reason=response.stop_reason, input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens, text=response.message.text, tool_calls=response.message.tool_calls,
        )
        self._calls += 1

    def after_tool(self, call: Any, result: Any) -> None:
        self.tracer.event(
            "tool_result", step=self._calls - 1, name=call.name, arguments=call.arguments,
            tool_call_id=result.tool_call_id, content=result.content, is_error=result.is_error,
        )

    def on_finish(self, result: Any) -> None:
        self.tracer.event(
            "stop", stop_reason=result.stop_reason, steps=len(result.steps), input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens, error=result.error, final_text=result.final_text,
        )
