"""The agent loop: call the model, run the tools it asks for, repeat until it stops
or a limit is reached. The loop never raises for limits or tool failures."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterator, Literal

from harnessy.context import ContextManager
from harnessy.cost import PRICES, Price, cost_usd, price_for
from harnessy.hooks import Block, Hook, HookRunner
from harnessy.models.base import Model
from harnessy.safety import check_trifecta
from harnessy.streaming import Event, stream_agent
from harnessy.tools.registry import ToolRegistry
from harnessy.tracer import TraceHook, Tracer
from harnessy.types import Message, ModelResponse, Tool, ToolCall, ToolResult, ToolSpec, Usage

RunStopReason = Literal["end_turn", "max_steps", "max_tokens", "timeout", "refused", "model_error", "blocked", "max_cost"]


@dataclass(frozen=True)
class Step:
    index: int
    response: ModelResponse
    tool_results: tuple[ToolResult, ...] = ()


@dataclass
class RunResult:
    final_text: str
    stop_reason: RunStopReason
    steps: list[Step]
    usage: Usage
    messages: list[Message]
    error: str | None = None
    cost_usd: float = 0.0


@dataclass
class Agent:
    model: Model
    tools: list[Tool] | tuple[Tool, ...] = ()
    system: str | None = None
    max_steps: int = 10
    max_tokens_total: int = 100_000
    timeout_s: float = 120.0
    clock: Callable[[], float] = time.monotonic
    verbose: bool = False
    printer: Callable[[str], object] = print
    context: ContextManager | None = None
    tracer: Tracer | None = None
    hooks: list[Hook] | tuple[Hook, ...] = ()
    max_cost_usd: float | None = None
    prices: dict[str, Price] = field(default_factory=lambda: dict(PRICES))
    _registry: ToolRegistry = field(init=False, repr=False)
    _hooks: HookRunner = field(init=False, repr=False)
    _price: Price | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._registry = ToolRegistry(self.tools)
        self._hooks = HookRunner([*self.hooks, *([TraceHook(self.tracer)] if self.tracer else [])])
        self._price = price_for(self.model.name, self.prices)
        if self.max_cost_usd is not None and self._price is None:
            raise ValueError(f"No price for model '{self.model.name}': add it to prices, or drop max_cost_usd.")
        check_trifecta(self.tools, self.hooks)

    # --- Week 2 exercise ---------------------------------------------------------------

    def run(self, task: str) -> RunResult:
        messages: list[Message] = [Message(role="user", text=task)]
        steps: list[Step] = []
        usage = Usage()
        specs = self._registry.specs()
        start = self.clock()

        def cost() -> float:
            return cost_usd(usage, self._price) if self._price else 0.0

        def finish(reason: RunStopReason, text: str = "", error: str | None = None) -> RunResult:
            result = RunResult(text, reason, steps, usage, messages, error, cost())
            self._hooks.on_finish(result)
            return result

        self._hooks.on_start(self, task)

        while True:
            if len(steps) >= self.max_steps:
                return finish("max_steps")
            if usage.total >= self.max_tokens_total:
                return finish("max_tokens")
            if self.clock() - start >= self.timeout_s:
                return finish("timeout")
            if self.max_cost_usd is not None and cost() >= self.max_cost_usd:
                return finish("max_cost")

            try:
                view = self.context.prepare(messages) if self.context else messages
                view = self._hooks.before_model(view)
                if isinstance(view, Block):
                    return finish("blocked", error=view.reason)
                response = self._hooks.after_model(self.model.complete(view, specs, self.system))
            except Exception as e:  # any model failure ends the run cleanly
                return finish("model_error", error=f"{type(e).__name__}: {e}")

            usage = usage + response.usage
            messages.append(response.message)

            # Run tools only from a reply that finished cleanly: a cut-off, failed or refused
            # reply may hold a half-written call.
            if response.message.tool_calls and response.stop_reason not in ("max_tokens", "error", "refused"):
                results = tuple(self._run_tool(call) for call in response.message.tool_calls)
                messages.append(Message(role="user", tool_results=results))
                steps.append(Step(len(steps), response, results))
                self._log(steps[-1])
                continue

            steps.append(Step(len(steps), response))
            self._log(steps[-1])
            text = response.message.text
            if response.stop_reason == "refused":
                return finish("refused", text)
            if response.stop_reason in ("error", "max_tokens"):
                return finish("model_error", text, error=f"model stopped with '{response.stop_reason}'")
            rejection = self._hooks.on_stop(RunResult(text, "end_turn", steps, usage, messages, cost_usd=cost()))
            if rejection:
                messages.append(Message(role="user", text=rejection))
                continue
            return finish("end_turn", text)

    def stream(self, task: str) -> Iterator[Event]:
        """Run the task and yield TextDelta, ToolStart, ToolEnd and finally Done events (week 7)."""
        return stream_agent(self, task)

    def _run_tool(self, call: ToolCall) -> ToolResult:
        checked = self._hooks.before_tool(call)
        if isinstance(checked, Block):
            return self._hooks.after_tool(call, ToolResult(call.id, checked.reason, is_error=True))
        return self._hooks.after_tool(checked, self._registry.call(checked))

    # --- Given -------------------------------------------------------------------------

    def _log(self, step: Step) -> None:
        if not self.verbose:
            return
        r = step.response
        calls = ", ".join(f"{c.name}({c.arguments})" for c in r.message.tool_calls) or "-"
        text = r.message.text.replace("\n", " ")
        if len(text) > 80:
            text = text[:77] + "..."
        self.printer(
            f"[step {step.index}] stop={r.stop_reason} tokens={r.usage.input_tokens}/{r.usage.output_tokens} "
            f"calls={calls} text={text!r}"
        )
        for res in step.tool_results:
            flag = "ERROR " if res.is_error else ""
            self.printer(f"    -> {res.tool_call_id}: {flag}{res.content[:80]}")
