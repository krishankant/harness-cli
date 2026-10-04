"""Permissions: four modes, allow/deny rules, and the human at the prompt.

PermissionHook IS an ApprovalHook (week 6), so the lethal-trifecta check (week 7) sees a
decision for every tool that can send data out: "ask" or "deny", in every mode. In bypass
mode those tools stay at "ask" and the hook itself says yes, so turning approvals off is a
visible choice in code, not a hole in the check."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Callable, Iterable

from harness_cli.config import MODES
from harness_cli.tools import KIND
from harnessy.approvals import ApprovalHook, Decision
from harnessy.hooks import Block
from harnessy.types import ToolCall

# mode -> kind -> decision. Tools not in KIND (MCP tools) count as "execute".
# spawn_subagent ("agent") carries every trifecta leg of the tools it can hand out, so the
# week 7 check needs "ask" for it. PermissionHook approves it without asking the human,
# because the child runs under this same hook and asks for each risky call itself.
TABLE: dict[str, dict[str, Decision]] = {
    "default": {"read": "allow", "edit": "ask", "execute": "ask", "agent": "ask"},
    "accept-edits": {"read": "allow", "edit": "allow", "execute": "ask", "agent": "ask"},
    "plan": {"read": "allow", "edit": "deny", "execute": "deny", "agent": "deny"},
    "bypass": {"read": "allow", "edit": "allow", "execute": "ask", "agent": "ask"},
}
MAIN_ARGS = ("command", "path", "pattern", "url", "task")

# What ask_human returns: "y" once, "n" no, "a" always allow this tool for the session.
AskHuman = Callable[[ToolCall], str]


def kind_of(name: str) -> str:
    return KIND.get(name, "execute")


def policy_for(mode: str, tool_names: Iterable[str]) -> dict[str, Decision]:
    if mode not in TABLE:
        raise ValueError(f"unknown permission mode {mode!r}: use one of {', '.join(MODES)}")
    return {name: TABLE[mode][kind_of(name)] for name in tool_names}


def main_argument(call: ToolCall) -> str:
    for key in MAIN_ARGS:
        if isinstance(call.arguments.get(key), str):
            return call.arguments[key]
    return next((v for v in call.arguments.values() if isinstance(v, str)), "")


@dataclass(frozen=True)
class Rule:
    """`tool` or `tool(pattern)`. Both parts are fnmatch globs; the pattern is matched against
    the call's main argument (the command for run_shell, the path for file tools)."""

    tool: str
    pattern: str | None = None

    @classmethod
    def parse(cls, text: str) -> Rule:
        text = text.strip()
        if "(" not in text:
            return cls(text)
        if not text.endswith(")"):
            raise ValueError(f"bad permission rule {text!r}: expected tool or tool(pattern)")
        name, _, pattern = text[:-1].partition("(")
        return cls(name.strip(), pattern)

    def matches(self, call: ToolCall) -> bool:
        if not fnmatch.fnmatchcase(call.name, self.tool):
            return False
        return self.pattern is None or fnmatch.fnmatchcase(main_argument(call), self.pattern)

    def __str__(self) -> str:
        return self.tool if self.pattern is None else f"{self.tool}({self.pattern})"


class PermissionHook(ApprovalHook):
    def effective(self, name: str) -> str:
        """The decision as the user experiences it (for /tools)."""
        if name in self.always:
            return "allow (always)"
        decision = self.policy.get(name, self.default)
        if decision == "ask" and (self.mode == "bypass" or kind_of(name) == "agent"):
            return "allow (guarded)" if kind_of(name) == "agent" else "allow (bypass)"
        return decision

    def __init__(self, mode: str, tool_names: Iterable[str], allow: Iterable[str] = (), deny: Iterable[str] = (), ask_human: AskHuman | None = None):
        self.tool_names = list(tool_names)
        super().__init__(policy_for(mode, self.tool_names), approver=None, default="ask")
        self.mode = mode
        self.allow = [Rule.parse(r) for r in allow]
        self.deny = [Rule.parse(r) for r in deny]
        self.ask_human = ask_human
        self.always: set[str] = set()

    def set_mode(self, mode: str) -> None:
        self.policy = policy_for(mode, self.tool_names)
        self.mode = mode

    def add_tools(self, names: Iterable[str]) -> None:
        self.tool_names.extend(n for n in names if n not in self.tool_names)
        self.policy = policy_for(self.mode, self.tool_names)

    def before_tool(self, call: ToolCall) -> Block | None:
        name = call.name
        decision = self.policy.get(name, self.default)
        if decision == "deny":
            return Block(f"'{name}' is not allowed in {self.mode} mode. Say what you would do instead, or ask the user to switch modes.")
        rule = next((r for r in self.deny if r.matches(call)), None)
        if rule:
            return Block(f"'{name}' is blocked by the permission rule {rule}. Don't retry it; find another way or ask the user.")
        if decision == "allow" or self.mode == "bypass" or name in self.always or kind_of(name) == "agent":
            return None
        if any(r.matches(call) for r in self.allow):
            return None
        if self.ask_human is None:
            return Block(
                f"'{name}' needs approval and nobody can be asked in this run. The user can allow it with "
                f"--allowed-tools '{name}', a permissions.allow rule, or --permission-mode."
            )
        answer = self.ask_human(call)
        if answer == "a":
            self.always.add(name)
            return None
        if answer == "y":
            return None
        return Block(f"The user declined '{name}'. Don't retry it; ask what they want instead.")
