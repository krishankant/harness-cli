from harnessy.types import Message, ToolCall, ToolResult

TASK = Message("user", text="Read the notes and report.")


def history(pairs: int, size: int = 400, result_size: int = 400) -> list[Message]:
    """The task, then `pairs` × (assistant turn with text + one call, user turn with its result)."""
    msgs = [TASK]
    for i in range(pairs):
        msgs.append(Message("assistant", text="a" * size, tool_calls=(ToolCall(f"c{i}", "read_file", {"n": i}),)))
        msgs.append(Message("user", tool_results=(ToolResult(f"c{i}", "r" * result_size),)))
    return msgs
