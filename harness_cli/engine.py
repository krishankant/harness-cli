"""The engine: run one chat turn on a worker thread and hand back events.

Everything the CLI shows comes out of Engine.turn as events, in order: TextDelta, ToolStart,
ToolEnd (from harnessy.streaming, week 7), ApprovalRequest (when a tool needs a yes or no),
and finally Done. Approval requests travel through the same queue as the text, so the
consumer (the REPL, or headless mode) prints everything before a prompt before it asks."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from harness_cli.permissions import PermissionHook
from harnessy.context import ContextManager
from harnessy.cost import PRICES, price_for
from harnessy.hooks import Block, Hook
from harnessy.loop import Agent
from harnessy.models.base import Model
from harnessy.streaming import Done, StreamingModel, TextDelta, ToolEnd, ToolStart
from harnessy.types import Message, Tool, ToolCall, ToolResult, Usage

__all__ = ["ApprovalRequest", "Done", "Engine", "TextDelta", "ToolEnd", "ToolStart"]

TURN_TIMEOUT_S = 3600.0
TURN_MAX_TOKENS = 10_000_000  # per turn; max_steps and max_cost_usd are the real limits


@dataclass(frozen=True)
class ApprovalRequest:
    """A tool call waiting for the human. Put True or False on reply."""

    call: ToolCall
    reply: queue.Queue = field(default_factory=queue.Queue, compare=False)


class _Cancel(Hook):
    def __init__(self) -> None:
        self.flag = threading.Event()

    def before_model(self, view: list[Message]) -> Block | None:
        return Block("interrupted by the user") if self.flag.is_set() else None

    def before_tool(self, call: ToolCall) -> Block | None:
        return Block("Interrupted by the user before this tool ran.") if self.flag.is_set() else None


class _Emit(Hook):
    """Tool events. It runs after the permission hook, so ToolStart means the tool really runs."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def before_tool(self, call: ToolCall) -> None:
        self.engine._put(ToolStart(call))

    def after_tool(self, call: ToolCall, result: ToolResult) -> None:
        self.engine._put(ToolEnd(call, result))


class Engine:
    def __init__(
        self,
        model: Model,
        tools: Iterable[Tool],
        system: str | None,
        mode: str = "default",
        interactive: bool = True,
        allow: Iterable[str] = (),
        deny: Iterable[str] = (),
        hooks: Iterable[Hook] = (),
        max_steps: int = 50,
        max_cost_usd: float | None = None,
        context_budget_tokens: int = 120_000,
        permissions: PermissionHook | None = None,
    ):
        self.model = model
        self.tools = list(tools)
        self.system = system
        self.permissions = permissions or PermissionHook(mode, [t.name for t in self.tools], allow, deny)
        if interactive:
            self.permissions.ask_human = self._ask
        self.extra_hooks = list(hooks)
        self.max_steps = max_steps
        self.max_cost_usd = max_cost_usd
        self.context = ContextManager(budget_tokens=context_budget_tokens)
        self.usage = Usage()
        self.cost_usd = 0.0
        self._events: queue.Queue[Any] | None = None
        self._cancel = _Cancel()

    # --- what the REPL changes between turns ---

    def priced(self) -> bool:
        return price_for(self.model.name, PRICES) is not None

    def reset_context(self) -> None:
        self.context = ContextManager(budget_tokens=self.context.budget_tokens)

    # --- one turn ---

    def turn(self, prompt: str, history: list[Message]) -> Iterator[Any]:
        """Run one turn on a worker thread; yield its events, ending with Done(RunResult)."""
        events: queue.Queue[Any] = queue.Queue()
        self._events = events
        self._cancel = _Cancel()
        agent = Agent(
            StreamingModel(self.model, lambda text: events.put(TextDelta(text))),
            tools=self.tools,
            system=self.system,
            max_steps=self.max_steps,
            max_tokens_total=TURN_MAX_TOKENS,
            timeout_s=TURN_TIMEOUT_S,
            context=self.context,
            hooks=[self._cancel, self.permissions, *self.extra_hooks, _Emit(self)],
            max_cost_usd=self._remaining_budget(),
        )

        def work() -> None:
            try:
                events.put(Done(agent.run(prompt, history=list(history))))
            except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread
                events.put(e)

        threading.Thread(target=work, daemon=True, name="harness-turn").start()
        while True:
            item = events.get()
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, Done):
                self.usage = self.usage + item.result.usage
                self.cost_usd += item.result.cost_usd
                yield item
                return
            yield item

    def cancel(self) -> None:
        """Stop the running turn at the next model call or tool call."""
        self._cancel.flag.set()

    # --- internals ---

    def _remaining_budget(self) -> float | None:
        if self.max_cost_usd is None or not self.priced():
            return None
        return max(self.max_cost_usd - self.cost_usd, 0.0)

    def _put(self, event: Any) -> None:
        if self._events is not None:
            self._events.put(event)

    def _ask(self, call: ToolCall) -> str:
        """Called on the worker thread: hand the question to the consumer and wait."""
        request = ApprovalRequest(call)
        self._put(request)
        answer = request.reply.get()
        if answer in ("y", "n", "a"):
            return answer
        return "y" if answer else "n"
