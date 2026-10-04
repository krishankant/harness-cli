"""Week 5: one traced run read as a timeline, then an eval whose score moves when one thing changes.

Run from the repo root:  uv run python -m scripts.week5_demo [--provider anthropic|openai]
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402

from harnessy.evals.runner import aggregate, compare, format_table, run_evals, run_trial  # noqa: E402
from harnessy.evals.tasks import load_tasks  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402
from harnessy.tracer import format_timeline, load_trace  # noqa: E402

PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}
TASKS = Path(__file__).resolve().parent.parent / "evals" / "tasks"
PICKED = ("e02", "m02", "m04")  # file tasks with regex/file checks, so no judge model is needed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=list(PROVIDERS), default="anthropic")
    args = parser.parse_args()
    try:
        model = PROVIDERS[args.provider]()
        tasks = [t for t in load_tasks(TASKS) if t.id.startswith(PICKED)]
        with tempfile.TemporaryDirectory() as traces:
            print(f"== 1. one traced run ({model.name})")
            sums = next(t for t in tasks if t.id.startswith("m04"))
            record = run_trial(sums, model, 1, trace_dir=traces)
            print(format_timeline(load_trace(record.trace)))
            print(f"graded: {'PASS' if record.passed else 'FAIL'}  answer={record.answer!r}")

            print(f"\n== 2. an eval: {len(tasks)} tasks, as written")
            before = aggregate(run_evals(tasks, lambda: model))
            print(format_table(before))

            print("\n== 3. the same tasks with max_steps=1 (one change, measured)")
            after = aggregate(run_evals([replace(t, max_steps=1) for t in tasks], lambda: model))
            print(format_table(after))
            print("\nwhat moved (overall, and every pass rate):")
            moved = [line for line in compare(before, after) if line.startswith("overall") or "pass_rate" in line]
            for line in moved or ["nothing"]:
                print(f"  {line}")
    except NotImplementedError as e:
        print(f"Finish the exercises first ({e})")
        return 1
    except Exception as e:
        print(f"{args.provider} failed: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
