"""Approvals (week 6): a policy per tool (allow, ask or deny), enforced by a hook, so risky tools
wait for a human. Safety lives in code, not in the prompt."""

from __future__ import annotations

import json
from typing import Callable, Literal
from urllib.parse import urlparse

from harnessy.hooks import Block, Hook
from harnessy.types import ToolCall

Decision = Literal["allow", "ask", "deny"]
_DECISIONS = ("allow", "ask", "deny")


# --- Given -----------------------------------------------------------------------------


def terminal_approver(call: ToolCall, input_fn: Callable[[str], str] = input, printer: Callable[..., object] = print) -> bool:
    """Show the call and ask y/N on the terminal."""
    printer(f"\nThe agent wants to run {call.name}({json.dumps(call.arguments)[:300]})")
    return input_fn("Allow? [y/N] ").strip().lower() in ("y", "yes")


def host_approver(hosts: list[str]) -> Callable[[ToolCall], bool]:
    """An approver that allows a call only if its "url" argument points at one of these hosts
    ("host:port" as in the URL). Anything without a url is declined."""
    allowed = set(hosts)

    def approve(call: ToolCall) -> bool:
        return urlparse(str(call.arguments.get("url", ""))).netloc in allowed

    return approve


class ApprovalHook(Hook):
    def __init__(self, policy: dict[str, Decision], approver: Callable[[ToolCall], bool] | None = None, default: Decision = "allow"):
        bad = sorted({d for d in [*policy.values(), default] if d not in _DECISIONS})
        if bad:
            raise ValueError(f"policy values must be allow, ask or deny, not: {', '.join(bad)}")
        self.policy = dict(policy)
        self.approver = approver
        self.default = default

    # --- Week 6 exercise ---

    def before_tool(self, call: ToolCall) -> Block | None:
        """Look up the call's tool in self.policy (self.default if absent):
        - "deny" -> Block("'<name>' is not allowed by policy.")
        - "ask" with no approver -> Block("'<name>' needs approval, and no approver is set.")
        - "ask" and self.approver(call) is False ->
          Block("The user declined '<name>'. Ask what they want instead, or try another way.")
        - otherwise None (let it run).
        """
        decision = self.policy.get(call.name, self.default)
        if decision == "deny":
            return Block(f"'{call.name}' is not allowed by policy.")
        if decision == "ask":
            if self.approver is None:
                return Block(f"'{call.name}' needs approval, and no approver is set.")
            if not self.approver(call):
                return Block(f"The user declined '{call.name}'. Ask what they want instead, or try another way.")
        return None
