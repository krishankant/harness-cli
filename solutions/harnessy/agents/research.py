"""The research agent (week 8): answers questions from the local web and cites its pages."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from harnessy.approvals import ApprovalHook, host_approver
from harnessy.context import ContextManager
from harnessy.loop import Agent
from harnessy.memory import MemoryStore, memory_tools
from harnessy.models.base import Model
from harnessy.subagents import subagent_tool
from harnessy.tools.localweb import LocalWeb, web_tools
from harnessy.tools.web import http_get
from harnessy.types import ToolCall

SYSTEM = (
    "You are a research assistant with access to a small web. Find answers with web_search, read "
    "the pages you rely on with http_get, and answer briefly. Cite every page you used by its full "
    "URL (http://...), exactly as the search results show it. Never cite a page you didn't read. "
    "If the pages don't say, say that you couldn't find it."
)


# --- Given -----------------------------------------------------------------------------


def research_approver(web: LocalWeb) -> Callable[[ToolCall], bool]:
    """Approve http_get only to the local web, and spawn_subagent always: the helper carries
    the same approval hook, so its own http_get calls are checked too."""
    local = host_approver([web.host])

    def approve(call: ToolCall) -> bool:
        return call.name == "spawn_subagent" or local(call)

    return approve


# --- Week 8 exercise -------------------------------------------------------------------


def make_agent(model: Model, workspace: str | Path, web: LocalWeb) -> Agent:
    """The research agent. Configuration only:

    - guard = ApprovalHook({"http_get": "ask", "spawn_subagent": "ask"}, approver=research_approver(web)).
      With memory (private data), web pages (untrusted input) and http_get (a way out), this
      agent IS the lethal trifecta, so every way out needs the guard; spawn_subagent inherits
      http_get's tags, so it needs it too.
    - readers = web_tools(web) + [http_get]
    - tools, in this order: readers, memory_tools(MemoryStore(workspace / ".memory.json")),
      subagent_tool(model, readers, hooks=[guard], max_steps=8)
    - Agent(model, tools, system=SYSTEM, hooks=[guard], max_steps=15,
            context=ContextManager(budget_tokens=20_000))
    """
    guard = ApprovalHook({"http_get": "ask", "spawn_subagent": "ask"}, approver=research_approver(web))
    readers = [*web_tools(web), http_get]
    tools = [
        *readers,
        *memory_tools(MemoryStore(Path(workspace) / ".memory.json")),
        subagent_tool(model, readers, hooks=[guard], max_steps=8),
    ]
    return Agent(model, tools=tools, system=SYSTEM, hooks=[guard], max_steps=15, context=ContextManager(budget_tokens=20_000))
