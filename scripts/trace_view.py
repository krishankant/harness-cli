"""Print one traced run as a timeline.

Run from the repo root:  uv run python -m scripts.trace_view <trace.jsonl> [--run RUN_ID]
"""

import argparse
import sys

from harnessy.tracer import format_timeline, load_trace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--run", help="run id (default: the last run in the file)")
    args = parser.parse_args()
    events = load_trace(args.path, args.run)
    if not events:
        print(f"no events in {args.path}")
        return 1
    print(format_timeline(events))
    return 0


if __name__ == "__main__":
    sys.exit(main())
