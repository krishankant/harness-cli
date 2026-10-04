"""Streaming (week 7): see text as the model writes it, and tool calls as they happen.

Built on hooks and a background thread, so the loop you wrote doesn't change."""

from __future__ import annotations

import dataclasses
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from harnessy.hooks import Hook
from harnessy.types import Message, ModelResponse, ToolCall, ToolResult, ToolSpec


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolStart:
    call: ToolCall


@dataclass(frozen=True)
class ToolEnd:
    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class Done:
    result: Any  # a RunResult


Event = TextDelta | ToolStart | ToolEnd | Done


# --- Week 7 exercise -------------------------------------------------------------------


def collect_stream(items: Iterable[str | ModelResponse], on_text: Callable[[str], object]) -> ModelResponse:
    """Call on_text for every str item and return the ModelResponse (the last item). If the
    stream ends without one, raise RuntimeError("stream ended without a response")."""
    final = None
    for item in items:
        if isinstance(item, ModelResponse):
            final = item
        else:
            on_text(item)
    if final is None:
        raise RuntimeError("stream ended without a response")
    return final


# --- Given -----------------------------------------------------------------------------


class StreamingModel:
    """Wraps a model: streams through model.stream when it has one, else sends the whole text
    at the end as one chunk."""

    def __init__(self, model: Any, on_text: Callable[[str], object]):
        self.model = model
        self.name = model.name
        self.on_text = on_text

    def complete(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None) -> ModelResponse:
        stream = getattr(self.model, "stream", None)
        if stream is not None:
            return collect_stream(stream(messages, tools, system), self.on_text)
        response = self.model.complete(messages, tools, system)
        if response.message.text:
            self.on_text(response.message.text)
        return response


class _StreamHook(Hook):
    def __init__(self, emit: Callable[[Any], object]):
        self.emit = emit

    def before_tool(self, call: ToolCall) -> None:
        self.emit(ToolStart(call))

    def after_tool(self, call: ToolCall, result: ToolResult) -> None:
        self.emit(ToolEnd(call, result))


# --- Week 7 exercise -------------------------------------------------------------------


def stream_agent(agent: Any, task: str) -> Iterator[Event]:
    """Run the agent on task and yield events as they happen.

    1. events = queue.Queue().
    2. A copy of the agent with dataclasses.replace: model=StreamingModel(agent.model,
       lambda text: events.put(TextDelta(text))) and hooks=[*agent.hooks, _StreamHook(events.put)].
       (replace calls __post_init__ again, so the copy gets its own registry, hooks and tracer.)
    3. Run copy.run(task) in a threading.Thread(daemon=True); when it returns, put Done(result);
       if it raises, put the exception itself.
    4. Yield from the queue until Done (yield it too, then stop). If you get an exception,
       raise it here, in the caller's thread.
    """
    events: queue.Queue[Any] = queue.Queue()
    copy = dataclasses.replace(
        agent,
        model=StreamingModel(agent.model, lambda text: events.put(TextDelta(text))),
        hooks=[*agent.hooks, _StreamHook(events.put)],
    )

    def work() -> None:
        try:
            events.put(Done(copy.run(task)))
        except BaseException as e:  # noqa: BLE001 - handed to the caller's thread
            events.put(e)

    threading.Thread(target=work, daemon=True).start()
    while True:
        item = events.get()
        if isinstance(item, BaseException):
            raise item
        yield item
        if isinstance(item, Done):
            return
