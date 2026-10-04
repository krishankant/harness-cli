"""Week 8: the three capstone agents, one task each, on the same harness.

Run from the repo root:  uv run python -m scripts.week8_demo [--provider anthropic|openai]
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from harnessy.evals.runner import run_trial  # noqa: E402
from harnessy.evals.tasks import load_task  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402
from harnessy.tracer import format_timeline, load_trace  # noqa: E402

PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}
CAPSTONE = Path(__file__).resolve().parent.parent / "evals" / "capstone"
PICKED = ("research/r02-ferry-time.yaml", "code/c01-mean.yaml", "data/d02-books-revenue.yaml")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=list(PROVIDERS), default="anthropic")
    args = parser.parse_args()
    try:
        model = PROVIDERS[args.provider]()
        total = 0.0
        with tempfile.TemporaryDirectory() as traces:
            for rel in PICKED:
                task = load_task(CAPSTONE / rel)
                print(f"\n== {task.agent} agent ({model.name}): {task.prompt}")
                record = run_trial(task, model, 1, trace_dir=traces)
                print(format_timeline(load_trace(record.trace)) if record.trace and Path(record.trace).exists() else "(no trace)")
                status = "PASS" if record.passed else "FAIL"
                print(f"graded: {status}  steps={record.steps}  cost=${record.cost_usd:.4f}" + (f"  error={record.error}" if record.error else ""))
                for check in record.checks:
                    print(f"  {'ok  ' if check['passed'] else 'FAIL'} {check['type']}: {check['detail']}")
                total += record.cost_usd
        print(f"\nthree agents, one loop, total cost ${total:.4f}")
    except NotImplementedError as e:
        print(f"Finish the exercises first ({e})")
        return 1
    except Exception as e:
        print(f"{args.provider} failed: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
