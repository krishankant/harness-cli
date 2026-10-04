"""Week 2 "done when": the loop answers a two-tool question on each provider.

Run from the repo root:  uv run python -m scripts.week2_demo [--provider anthropic|openai|both]
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import datetime  # noqa: E402
import sys  # noqa: E402

from harnessy.loop import Agent, Tool  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402
from harnessy.types import ToolSpec  # noqa: E402

TASK = "What is 17 + 25, and what time is it?"
SYSTEM = "Answer using the tools. Be brief."


def add(a: int, b: int) -> str:
    return str(a + b)


def get_time() -> str:
    return datetime.datetime.now().strftime("%H:%M")


TOOLS = [
    Tool(
        ToolSpec(
            "add",
            "Add two integers and return the sum.",
            {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
        ),
        add,
    ),
    Tool(ToolSpec("get_time", "Return the current local time as HH:MM.", {"type": "object", "properties": {}}), get_time),
]

PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["anthropic", "openai", "both"], default="both")
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args()
    names = list(PROVIDERS) if args.provider == "both" else [args.provider]
    ok = 0
    for name in names:
        try:
            agent = Agent(PROVIDERS[name](), tools=TOOLS, system=SYSTEM, max_steps=args.max_steps, verbose=True)
            print(f"\n== {agent.model.name}")
            r = agent.run(TASK)
        except NotImplementedError as e:
            print(f"\n{name}: finish the exercise first ({e})")
            continue
        except Exception as e:
            print(f"\n{name} failed to start: {type(e).__name__}: {e}")
            continue
        print(f"stop={r.stop_reason} steps={len(r.steps)} tokens={r.usage.total}" + (f" error={r.error}" if r.error else ""))
        print(f"answer: {r.final_text}")
        ok += r.stop_reason == "end_turn"
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
