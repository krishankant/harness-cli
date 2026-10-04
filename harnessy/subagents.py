"""Subagents (week 6): hand a sub-task to a child agent with a fresh context. The parent sees
only the child's final answer, so its own context stays small."""

from __future__ import annotations

from typing import Iterable

from harnessy.hooks import Hook
from harnessy.loop import Agent
from harnessy.models.base import Model
from harnessy.tools.schema import tool
from harnessy.types import Tool

SUBAGENT_SYSTEM = (
    "You are a focused helper doing one sub-task for another agent. Use your tools, then reply with a "
    "short, complete answer: the other agent sees only that reply."
)


# --- Week 6 exercise -------------------------------------------------------------------


def subagent_tool(
    model: Model, tools: list[Tool], system: str = SUBAGENT_SYSTEM, max_steps: int = 8, hooks: Iterable[Hook] = ()
) -> Tool:
    """Return a tool named spawn_subagent, built with @tool(timeout_s=600) (a child run takes a
    while), with this signature and docstring:

        def spawn_subagent(task: str, tools: list[str] | None = None) -> str:
            \"\"\"Hand a self-contained sub-task to a helper agent with a fresh context. It returns only its final answer.

            Args:
                task: Everything the helper needs to know: it can't see this conversation.
                tools: Names of the tools the helper may use (default: all of them).
            \"\"\"

    When called:
    - names = the given tool names, or all of `tools` if None. Any unknown name ->
      raise ValueError("unknown tools: <unknown joined ', '>. Available: <all names joined ', '>").
    - Run a NEW Agent(model, tools=<those tools>, system=system, max_steps=max_steps, hooks=list(hooks))
      on task. The child gets only the hooks passed here: without your ApprovalHook, a parent could
      get around its own policy by handing the risky call to a helper.
    - end_turn -> return its final text, or "(the subagent returned no text)" if empty.
    - any other stop -> "The subagent stopped early (<stop_reason>[: <error>]). Partial answer: <final text>".
    - The tool's tags are the union of `tools`' tags (week 7): delegating must not hide a
      trifecta leg. Pass tags=frozenset().union(*(t.tags for t in tools)) to @tool.
    """
    available = {t.name: t for t in tools}
    child_hooks = list(hooks)

    @tool(timeout_s=600, tags=frozenset().union(*(t.tags for t in tools)))
    def spawn_subagent(task: str, tools: list[str] | None = None) -> str:
        """Hand a self-contained sub-task to a helper agent with a fresh context. It returns only its final answer.

        Args:
            task: Everything the helper needs to know: it can't see this conversation.
            tools: Names of the tools the helper may use (default: all of them).
        """
        names = list(available) if tools is None else list(tools)
        unknown = [n for n in names if n not in available]
        if unknown:
            raise ValueError(f"unknown tools: {', '.join(unknown)}. Available: {', '.join(available) or 'none'}")
        result = Agent(model, tools=[available[n] for n in names], system=system, max_steps=max_steps, hooks=child_hooks).run(task)
        if result.stop_reason == "end_turn":
            return result.final_text or "(the subagent returned no text)"
        detail = f"{result.stop_reason}: {result.error}" if result.error else result.stop_reason
        return f"The subagent stopped early ({detail}). Partial answer: {result.final_text}"

    return spawn_subagent
