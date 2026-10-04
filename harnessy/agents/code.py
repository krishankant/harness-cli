"""The code agent (week 8): fixes a bug in a small repo until its tests pass."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from harnessy.approvals import ApprovalHook
from harnessy.hooks import StopCheck
from harnessy.loop import Agent
from harnessy.models.base import Model
from harnessy.tools.code import code_tools
from harnessy.tools.sandbox import run_command
from harnessy.types import ToolCall

SYSTEM = (
    "You fix bugs in a small Python project in your workspace. Read the code and the tests, find the "
    "bug, fix it with edit_file, and run the tests with run_tests until they pass. Never change the "
    "tests. Finish with one sentence saying what was wrong."
)


# --- Given -----------------------------------------------------------------------------


def trust_workspace_tests(call: ToolCall) -> bool:
    """Approve run_tests. run_tests runs code the model may have written, so it carries all three
    trifecta legs and needs a guard. Here we approve it on purpose: the repo is a throwaway eval
    workspace and the run is sandboxed (scrubbed environment, timeout). In production, run the
    tests in a container with no network, or ask a person."""
    return True


# --- Week 8 exercise -------------------------------------------------------------------


def make_agent(model: Model, workspace: str | Path) -> Agent:
    """The code agent. Configuration only:

    - tools = code_tools(workspace)
    - a StopCheck whose check runs the tests (run_command([sys.executable, "-m", "pytest", "-q",
      "-p", "no:cacheprovider"], workspace, timeout_s=120, max_output=1_000_000)) and returns None
      if they pass, else a message telling the model the tests still fail, with the last 1,500
      characters of the output. The agent can't say "done" until the tests pass (week 6).
    - run_tests is tagged like a shell (week 7), so the tools are the lethal trifecta: guard it with
      ApprovalHook({"run_tests": "ask"}, approver=trust_workspace_tests) (given, and read why)
    - Agent(model, tools, system=SYSTEM, hooks=[the ApprovalHook, that StopCheck], max_steps=20)
    """

    def tests_pass(result: Any) -> str | None:
        run = run_command(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], Path(workspace), timeout_s=120, max_output=1_000_000
        )
        if run.exit_code == 0:
            return None
        return "The tests still fail. Run run_tests, fix the code (not the tests), and try again.\n" + run.output[-1500:]

    guard = ApprovalHook({"run_tests": "ask"}, approver=trust_workspace_tests)
    return Agent(model, tools=code_tools(workspace), system=SYSTEM, hooks=[guard, StopCheck(tests_pass)], max_steps=20)
