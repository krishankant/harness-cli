"""A fake model that replays prepared responses. Use it to test the loop without
spending tokens, and to reproduce a bad run step by step."""

from __future__ import annotations

from dataclasses import dataclass

from harnessy.types import Message, ModelResponse, StopReason, ToolCall, ToolSpec, Usage


@dataclass(frozen=True)
class ScriptedCall:
    messages: list[Message]
    tools: list[ToolSpec]
    system: str | None


class ScriptedModel:
    name = "scripted"

    def __init__(self, responses: list[ModelResponse | Exception]):
        self._responses = list(responses)
        self.calls: list[ScriptedCall] = []

    def complete(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None) -> ModelResponse:
        self.calls.append(ScriptedCall(list(messages), list(tools), system))
        if not self._responses:
            raise RuntimeError("ScriptedModel ran out of responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def stream(self, messages: list[Message], tools: list[ToolSpec], system: str | None = None):
        """The scripted reply's text in 8-character chunks, then the reply (week 7)."""
        response = self.complete(messages, tools, system)
        text = response.message.text
        for i in range(0, len(text), 8):
            yield text[i : i + 8]
        yield response


def text_reply(text: str, input_tokens: int = 10, output_tokens: int = 5, stop_reason: StopReason = "end_turn") -> ModelResponse:
    return ModelResponse(Message(role="assistant", text=text), stop_reason, Usage(input_tokens, output_tokens))


def tool_reply(
    *calls: ToolCall,
    text: str = "",
    input_tokens: int = 10,
    output_tokens: int = 5,
    stop_reason: StopReason = "tool_use",
) -> ModelResponse:
    return ModelResponse(Message(role="assistant", text=text, tool_calls=calls), stop_reason, Usage(input_tokens, output_tokens))
