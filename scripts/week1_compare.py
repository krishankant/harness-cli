"""Week 1 "done when": the same question on two providers comes back in the same shape.

Run from the repo root:  uv run python -m scripts.week1_compare
"""

from dotenv import load_dotenv

load_dotenv()

import sys  # noqa: E402

from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402
from harnessy.types import Message, ModelResponse, ToolResult, ToolSpec  # noqa: E402

SYSTEM = "You are a careful assistant. Use the add tool for arithmetic."
QUESTION = "What is 17 + 25?"
ADD = ToolSpec(
    "add",
    "Add two integers and return the sum.",
    {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    },
)


def add(a: int, b: int) -> str:
    return str(a + b)


def show(label: str, r: ModelResponse) -> None:
    calls = [(c.name, c.arguments) for c in r.message.tool_calls]
    print(f"  {label}: {type(r).__name__} stop={r.stop_reason} text={r.message.text!r} "
          f"tool_calls={calls} usage={r.usage.input_tokens}/{r.usage.output_tokens}")


def run_one(model) -> None:
    print(f"\n== {model.name}")
    messages = [Message(role="user", text=QUESTION)]
    first = model.complete(messages, [ADD], SYSTEM)
    show("turn 1", first)
    if not first.message.tool_calls:
        return
    messages.append(first.message)
    results = []
    for c in first.message.tool_calls:
        try:
            results.append(ToolResult(c.id, add(**c.arguments)))
        except TypeError as e:
            results.append(ToolResult(c.id, f"Bad arguments: {e}", is_error=True))
    messages.append(Message(role="user", tool_results=tuple(results)))
    show("turn 2", model.complete(messages, [ADD], SYSTEM))


def main() -> int:
    ok = 0
    for factory in (AnthropicModel, OpenAIModel):
        try:
            run_one(factory())
            ok += 1
        except NotImplementedError as e:
            print(f"\n{factory.__name__}: finish the exercise first ({e})")
        except Exception as e:
            print(f"\n{factory.__name__} failed: {type(e).__name__}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
