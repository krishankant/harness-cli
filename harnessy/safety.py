"""The lethal trifecta (week 7): private data + untrusted input + a way to send data out means
an injected instruction can steal your data. The defence is architecture: refuse to build an
agent that has all three unless every way out needs approval."""

from __future__ import annotations

from typing import Iterable

from harnessy.approvals import ApprovalHook
from harnessy.hooks import Hook
from harnessy.types import Tool

TAGS = ("private_data", "untrusted_input", "external_send")


class TrifectaError(ValueError):
    pass


# --- Week 7 exercise -------------------------------------------------------------------


def check_trifecta(tools: Iterable[Tool], hooks: Iterable[Hook]) -> None:
    """Refuse an agent that has the lethal trifecta with an unguarded way out.

    - If the tools' tags together don't include all three TAGS: return (nothing to check).
    - Otherwise every tool tagged "external_send" must be guarded: some ApprovalHook in hooks
      decides "ask" or "deny" for it (its policy entry for the tool's name, else its default).
    - If any aren't, raise TrifectaError with a message that says this is the lethal trifecta
      (private data, untrusted input and a way to send data out), names the unguarded tools
      after "without approval: " joined with ", ", and says how to fix it (an ApprovalHook with
      'ask' or 'deny', or remove one of the three).
    """
    tools = list(tools)
    present = set().union(*(t.tags for t in tools)) if tools else set()
    if not set(TAGS) <= present:
        return
    approvals = [h for h in hooks if isinstance(h, ApprovalHook)]

    def guarded(name: str) -> bool:
        return any(h.policy.get(name, h.default) in ("ask", "deny") for h in approvals)

    unguarded = [t.name for t in tools if "external_send" in t.tags and not guarded(t.name)]
    if unguarded:
        raise TrifectaError(
            "This agent has the lethal trifecta: private data, untrusted input and a way to send data out. "
            f"These tools can send data out without approval: {', '.join(unguarded)}. "
            "Guard them with an ApprovalHook ('ask' or 'deny'), or remove one of the three."
        )
