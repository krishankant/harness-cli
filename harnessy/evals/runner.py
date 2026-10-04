"""The eval runner (week 5): run every task several times, grade each trial, and summarize.

Agents are random, so one good run proves little: pass rates over several trials are the
number to watch, and the saved summaries let you compare before and after a change."""

from __future__ import annotations

import tempfile
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from harnessy.evals.graders import grade
from harnessy.evals.tasks import EvalTask
from harnessy.loop import Agent
from harnessy.memory import MemoryStore, memory_tools
from harnessy.models.base import Model
from harnessy.tools.files import file_tools, resolve_inside
from harnessy.tracer import Tracer
from harnessy.types import Tool

DEFAULT_SYSTEM = (
    "You are a careful assistant working in a small workspace folder. Use the tools when they help. "
    "Finish with a short, direct answer."
)
METRICS = ("pass_rate", "mean_steps", "mean_tokens", "mean_cost_usd")


@dataclass
class TrialRecord:
    task_id: str
    difficulty: str
    trial: int
    passed: bool
    checks: list[dict[str, Any]]
    stop_reason: str
    steps: int
    input_tokens: int
    output_tokens: int
    error: str | None = None
    trace: str | None = None
    answer: str = ""
    cost_usd: float = 0.0


# --- Given -----------------------------------------------------------------------------


def build_tools(task: EvalTask, workspace: Path) -> list[Tool]:
    tools: list[Tool] = []
    if "files" in task.toolsets:
        tools += file_tools(workspace)
    if "memory" in task.toolsets:
        tools += memory_tools(MemoryStore(workspace / ".memory.json"))
    return tools


def find_corpus() -> Path:
    """evals/corpus/, found by walking up from this file (works from both trees)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "evals" / "corpus").is_dir():
            return parent / "evals" / "corpus"
    return Path("evals") / "corpus"


def run_trial(
    task: EvalTask,
    model: Model,
    trial: int,
    judge: Model | None = None,
    trace_dir: str | Path | None = None,
    corpus: str | Path | None = None,
) -> TrialRecord:
    """One trial in a fresh temporary workspace. Never raises: a crash is a failed record.
    A task with an agent (week 8) is built by that agent's make_agent; research trials get a
    LocalWeb on the corpus for the length of the trial."""
    trace = str(Path(trace_dir) / f"{task.id}-{trial}.jsonl") if trace_dir else None
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        workspace = Path(tmp)
        web = None
        try:
            for rel, text in task.files.items():
                target = resolve_inside(workspace, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            tracer = Tracer(trace) if trace else None
            if task.agent:
                # Imported here, not at the top: the week 5 runner shouldn't need week 8's modules.
                from harnessy.agents import AGENTS
                from harnessy.tools.localweb import LocalWeb

                context = {}
                if task.agent == "research":
                    web = stack.enter_context(LocalWeb(corpus or find_corpus()))
                    context["web"] = web
                agent = replace(AGENTS[task.agent](model, workspace, **context), tracer=tracer)
            else:
                agent = Agent(
                    model,
                    tools=build_tools(task, workspace),
                    system=task.system or DEFAULT_SYSTEM,
                    max_steps=task.max_steps,
                    tracer=tracer,
                )
            result = agent.run(task.prompt)
        except Exception as e:
            return TrialRecord(task.id, task.difficulty, trial, False, [], "crash", 0, 0, 0, f"{type(e).__name__}: {e}", trace)
        checks = []
        for check in task.checks:
            outcome = grade(check, result.final_text, workspace, judge, web)
            checks.append({"type": check["type"], "passed": outcome.passed, "detail": outcome.detail})
    return TrialRecord(
        task.id, task.difficulty, trial, all(c["passed"] for c in checks), checks, result.stop_reason, len(result.steps),
        result.usage.input_tokens, result.usage.output_tokens, result.error, trace, result.final_text,
        getattr(result, "cost_usd", 0.0),  # a week 5 loop has no costs yet
    )


def run_evals(
    tasks: list[EvalTask],
    make_model: Callable[[], Model],
    trials: int = 1,
    judge: Model | None = None,
    trace_dir: str | Path | None = None,
    on_record: Callable[[TrialRecord], object] | None = None,
) -> list[TrialRecord]:
    records = []
    for task in tasks:
        for trial in range(1, trials + 1):
            record = run_trial(task, make_model(), trial, judge, trace_dir)
            records.append(record)
            if on_record:
                on_record(record)
    return records


def format_table(summary: dict[str, Any]) -> str:
    rows = [("task", "level", "pass", "rate", "steps", "tokens", "cost")]
    for task_id, s in summary["tasks"].items():
        rows.append((task_id, s["difficulty"], f"{s['passed']}/{s['trials']}", f"{s['pass_rate']:.0%}", f"{s['mean_steps']:.1f}", f"{s['mean_tokens']:.0f}", f"${s.get('mean_cost_usd', 0.0):.4f}"))
    o = summary["overall"]
    rows.append(("OVERALL", "", f"{o['passed']}/{o['trials']}", f"{o['pass_rate']:.0%}", f"{o['mean_steps']:.1f}", f"{o['mean_tokens']:.0f}", f"${o.get('mean_cost_usd', 0.0):.4f}"))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(w) if i < 2 else cell.rjust(w) for i, (cell, w) in enumerate(zip(row, widths))) for row in rows
    )


# --- Week 5 exercise -------------------------------------------------------------------


def _stats(records: list[TrialRecord]) -> dict[str, Any]:
    n = len(records)
    passed = sum(r.passed for r in records)
    return {
        "trials": n,
        "passed": passed,
        "pass_rate": round(passed / n, 3) if n else 0.0,
        "mean_steps": round(sum(r.steps for r in records) / n, 1) if n else 0.0,
        "mean_tokens": round(sum(r.input_tokens + r.output_tokens for r in records) / n, 1) if n else 0.0,
        "mean_cost_usd": round(sum(r.cost_usd for r in records) / n, 4) if n else 0.0,
    }


def aggregate(records: list[TrialRecord]) -> dict[str, Any]:
    """Summarize trial records:
    {"tasks": {task_id: {"difficulty", "trials", "passed", "pass_rate", "mean_steps", "mean_tokens", "mean_cost_usd"}},
     "overall": {"trials", "passed", "pass_rate", "mean_steps", "mean_tokens", "mean_cost_usd"}}
    Tasks appear in first-seen order. pass_rate is rounded to 3 places, mean_steps and
    mean_tokens to 1, mean_cost_usd to 4; tokens are input + output. Empty groups give 0.0.
    """
    by_task: dict[str, list[TrialRecord]] = {}
    for r in records:
        by_task.setdefault(r.task_id, []).append(r)
    return {
        "tasks": {task_id: {"difficulty": recs[0].difficulty, **_stats(recs)} for task_id, recs in by_task.items()},
        "overall": _stats(records),
    }


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What changed between two summaries, one line per changed metric (METRICS, in order):
    "<label>: <metric> <old:g> -> <new:g> (<new - old:+g>)". First "overall", then every task
    id in either summary, sorted: in both -> its changed metrics; only in new -> "<id>: new task";
    only in old -> "<id>: removed". Nothing changed -> []. Skip a metric that is missing from
    either side (results saved before week 7 have no mean_cost_usd).
    """
    lines: list[str] = []

    def diff(label: str, a: dict[str, Any], b: dict[str, Any]) -> None:
        for m in METRICS:
            if m in a and m in b and a[m] != b[m]:
                lines.append(f"{label}: {m} {a[m]:g} -> {b[m]:g} ({b[m] - a[m]:+g})")

    diff("overall", old["overall"], new["overall"])
    for task_id in sorted(set(old["tasks"]) | set(new["tasks"])):
        if task_id not in old["tasks"]:
            lines.append(f"{task_id}: new task")
        elif task_id not in new["tasks"]:
            lines.append(f"{task_id}: removed")
        else:
            diff(task_id, old["tasks"][task_id], new["tasks"][task_id])
    return lines
