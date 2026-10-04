"""Week 3: an agent with @tool file tools, confined to a temporary workspace.

Run from the repo root:  uv run python -m scripts.week3_demo [--provider anthropic|openai|both]
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from harnessy.loop import Agent  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402
from harnessy.tools.files import file_tools  # noqa: E402

TASK = "Write a three-line haiku about tests to haiku.txt, then read the file back and tell me how many lines it has."
SYSTEM = "You work inside a small workspace folder. Use the tools. Be brief."
PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["anthropic", "openai", "both"], default="both")
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args()
    names = list(PROVIDERS) if args.provider == "both" else [args.provider]
    ok = 0
    for name in names:
        with tempfile.TemporaryDirectory() as workspace:
            try:
                agent = Agent(
                    PROVIDERS[name](), tools=file_tools(workspace), system=SYSTEM, max_steps=args.max_steps, verbose=True
                )
                print(f"\n== {agent.model.name}  (workspace {workspace})")
                r = agent.run(TASK)
            except NotImplementedError as e:
                print(f"\n{name}: finish the exercise first ({e})")
                continue
            except Exception as e:
                print(f"\n{name} failed to start: {type(e).__name__}: {e}")
                continue
            print(f"stop={r.stop_reason} steps={len(r.steps)} tokens={r.usage.total}" + (f" error={r.error}" if r.error else ""))
            print(f"answer: {r.final_text}")
            haiku = Path(workspace) / "haiku.txt"
            print("haiku.txt:\n" + (haiku.read_text() if haiku.exists() else "(not written)"))
            ok += r.stop_reason == "end_turn" and haiku.exists()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
