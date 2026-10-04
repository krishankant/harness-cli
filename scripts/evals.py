"""Week 5: run the eval suite against real models.

Run from the repo root:
    uv run python -m scripts.evals --tasks easy --trials 1          # cheap first run
    uv run python -m scripts.evals --provider both --trials 3       # the week 5 "done when"
    uv run python -m scripts.evals --suite capstone --trials 1      # week 8: the three agents
Results go to evals/results/ (git-ignored); each run is compared with the previous one.
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from dataclasses import asdict  # noqa: E402
from pathlib import Path  # noqa: E402

from harnessy.evals.runner import aggregate, compare, format_table, run_evals  # noqa: E402
from harnessy.evals.tasks import load_tasks  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SUITES = {"core": ROOT / "evals" / "tasks", "capstone": ROOT / "evals" / "capstone"}
RESULTS = ROOT / "evals" / "results"
PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}


def result_name(stamp: str, suite: str, provider: str) -> str:
    return f"{stamp}-{provider}.json" if suite == "core" else f"{stamp}-{suite}-{provider}.json"


def previous(suite: str, provider: str, before: str) -> dict | None:
    pattern = f"*Z-{provider}.json" if suite == "core" else f"*-{suite}-{provider}.json"
    files = sorted(p for p in RESULTS.glob(pattern) if p.name < before)
    return json.loads(files[-1].read_text()) if files else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["anthropic", "openai", "both"], default="both")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--tasks", help="a difficulty (easy/medium/hard) or an id prefix")
    parser.add_argument("--judge", choices=["anthropic", "openai", "none"], default="anthropic")
    parser.add_argument("--suite", choices=list(SUITES), default="core", help="core (weeks 5-7) or capstone (week 8)")
    args = parser.parse_args()
    try:
        tasks = load_tasks(SUITES[args.suite], args.tasks)
        if not tasks:
            print(f"no tasks match {args.tasks!r}")
            return 1
        judge = None if args.judge == "none" else PROVIDERS[args.judge]()
    except NotImplementedError as e:
        print(f"Finish the exercises first ({e})")
        return 1
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    names = list(PROVIDERS) if args.provider == "both" else [args.provider]
    for name in names:
        try:
            model = PROVIDERS[name]()
        except Exception as e:
            print(f"\n{name} failed to start: {type(e).__name__}: {e}")
            continue
        print(f"\n== {model.name}: {args.suite} suite, {len(tasks)} tasks x {args.trials} trials")

        def show(r) -> None:
            status = "PASS" if r.passed else "FAIL"
            print(f"  {status} {r.task_id} #{r.trial} steps={r.steps} stop={r.stop_reason}" + (f" error={r.error}" if r.error else ""))

        try:
            traces = RESULTS / "traces" / result_name(stamp, args.suite, name).removesuffix(".json")
            records = run_evals(tasks, lambda: model, args.trials, judge, traces, show)
        except NotImplementedError as e:
            print(f"Finish the exercises first ({e})")
            return 1
        summary = aggregate(records)
        print(format_table(summary))
        RESULTS.mkdir(parents=True, exist_ok=True)
        out = RESULTS / result_name(stamp, args.suite, name)
        out.write_text(json.dumps({"provider": name, "suite": args.suite, "model": model.name, "timestamp": stamp, "summary": summary,
                                   "records": [asdict(r) for r in records]}, indent=2))
        before = previous(args.suite, name, out.name)
        if before:
            changes = compare(before["summary"], summary)
            print(f"\nchanges since {before['timestamp']}:" if changes else f"\nno change since {before['timestamp']}")
            for line in changes:
                print("  " + line)
        print(f"saved {out.relative_to(ROOT)}; traces in {traces.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
