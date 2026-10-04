"""Week 4: the same long task with and without a ContextManager, then memory across two runs.

Run from the repo root:  uv run python -m scripts.week4_demo [--provider anthropic|openai] [--budget 3000]
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from harnessy.context import ContextManager  # noqa: E402
from harnessy.loop import Agent  # noqa: E402
from harnessy.memory import MemoryStore, memory_tools  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402
from harnessy.tools.files import file_tools  # noqa: E402

PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}
FILES = 8
TASK = (
    f"The folder notes/ has files 01.txt to {FILES:02d}.txt. Read them one at a time, in order, and tell me "
    "which file mentions a purple elephant."
)


def make_notes(root: Path) -> None:
    for i in range(1, FILES + 1):
        filler = "\n".join(f"Line {n}: routine notes about the quarterly plan." for n in range(60))
        extra = "\nAlso: a purple elephant was seen near the lake." if i == 6 else ""
        (root / "notes").mkdir(exist_ok=True)
        (root / "notes" / f"{i:02d}.txt").write_text(filler + extra)


def run(agent: Agent, task: str, label: str) -> None:
    r = agent.run(task)
    per_step = [s.response.usage.input_tokens for s in r.steps]
    print(f"\n-- {label}: stop={r.stop_reason} steps={len(r.steps)} total tokens={r.usage.total}")
    print(f"   input tokens per step: {per_step}")
    print(f"   answer: {r.final_text[:200]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=list(PROVIDERS), default="anthropic")
    parser.add_argument("--budget", type=int, default=3000)
    args = parser.parse_args()
    try:
        model = PROVIDERS[args.provider]()
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            make_notes(root)
            system = "You work inside a small workspace folder. Use the tools. Be brief."
            print(f"== {model.name}: long task, context budget {args.budget:,} estimated tokens")
            run(Agent(model, tools=file_tools(root), system=system, max_steps=15), TASK, "without ContextManager")
            cm = ContextManager(budget_tokens=args.budget)
            run(Agent(model, tools=file_tools(root), system=system, max_steps=15, context=cm), TASK, "with ContextManager")

            store = MemoryStore(root / "memory.json")
            print(f"\n== memory across runs ({store.path.name})")
            agent = Agent(model, tools=memory_tools(store), system="Use your memory tools. Be brief.", max_steps=5)
            run(agent, "My favourite colour is teal. Remember that for next time.", "run 1")
            run(agent, "What is my favourite colour? Check your memory.", "run 2")
            print(f"\nmemory.json: {store.path.read_text() if store.path.exists() else '(empty)'}")
    except NotImplementedError as e:
        print(f"Finish the exercises first ({e})")
        return 1
    except Exception as e:
        print(f"{args.provider} failed: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
