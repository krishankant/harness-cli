from __future__ import annotations

from typing import Protocol, runtime_checkable

from harnessy.types import Message, ModelResponse, ToolSpec


@runtime_checkable
class Model(Protocol):
    """Anything that can take a conversation and return the next assistant turn."""

    name: str

    def complete(
        self, messages: list[Message], tools: list[ToolSpec], system: str | None = None
    ) -> ModelResponse: ...
