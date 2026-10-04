"""Week 6: an approval prompt in your terminal, then a research task split across two subagents.

Run from the repo root:  uv run python -m scripts.week6_demo [--provider anthropic|openai] [--yes]
(--yes approves automatically, for running without a terminal.)
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from harnessy.approvals import ApprovalHook, terminal_approver  # noqa: E402
from harnessy.loop import Agent  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402
from harnessy.subagents import subagent_tool  # noqa: E402
from harnessy.todo import TodoList  # noqa: E402
from harnessy.tools.files import file_tools  # noqa: E402

PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}
NOTES = {
    "cats/note1.txt": "Cats sleep 12 to 16 hours a day and are most active at dawn and dusk.",
    "cats/note2.txt": "A group of cats is called a clowder. Most cats dislike water.",
    "dogs/note1.txt": "Dogs were domesticated at least 15,000 years ago, from wolves.",
    "dogs/note2.txt": "A dog's sense of smell is roughly 10,000 times stronger than a human's.",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=list(PROVIDERS), default="anthropic")
    parser.add_argument("--yes", action="store_true", help="approve every request automatically")
    args = parser.parse_args()
    try:
        model = PROVIDERS[args.provider]()
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            for rel, text in NOTES.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text)

            print(f"== 1. approval ({model.name})")
            approver = (lambda call: True) if args.yes else terminal_approver
            agent = Agent(
                model, tools=file_tools(root), system="You work in a small workspace folder. Be brief.",
                hooks=[ApprovalHook({"write_file": "ask"}, approver)], verbose=True,
            )
            r = agent.run("Write a one-line motto for a pet shop to motto.txt.")
            motto = root / "motto.txt"
            print(f"stop={r.stop_reason}  motto.txt: {motto.read_text() if motto.exists() else '(not written)'}")

            print("\n== 2. two subagents")
            readers = [t for t in file_tools(root) if t.name == "read_file"]
            todo = TodoList()
            parent = Agent(
                model,
                tools=[subagent_tool(model, readers), todo.tool()],
                system="You coordinate helpers. You can't read files yourself: give each helper one folder and ask for a summary.",
                hooks=[todo], max_steps=8, verbose=True,
            )
            r = parent.run(
                "The folders cats/ and dogs/ each hold note1.txt and note2.txt. Use one helper per folder to "
                "summarize it, then compare cats and dogs in three sentences."
            )
            print(f"\nstop={r.stop_reason} steps={len(r.steps)} tokens={r.usage.total} parent messages={len(r.messages)}")
            print(f"answer: {r.final_text}")
    except NotImplementedError as e:
        print(f"Finish the exercises first ({e})")
        return 1
    except Exception as e:
        print(f"{args.provider} failed: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
