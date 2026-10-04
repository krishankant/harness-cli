"""Provider-neutral types. Every adapter translates to and from these; nothing else in
harnessy ever sees a provider's own format."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refused", "error"]


@dataclass(frozen=True)
class ToolCall:
    """The model asking to run a tool. `id` links it to the matching ToolResult."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """What a tool returned. Failures are results too (is_error=True), never exceptions."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ProviderRaw:
    """A provider's own content for one assistant turn, kept so the adapter that produced
    it can send it back unchanged (for example Anthropic thinking blocks)."""

    provider: str
    content: Any


@dataclass(frozen=True)
class Message:
    """One turn. A user turn carries text and/or tool results; an assistant turn carries
    text and/or tool calls. The system prompt is not a message."""

    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    raw: ProviderRaw | None = None


@dataclass(frozen=True)
class ToolSpec:
    """What the model sees of a tool: its name, a description and a JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Tool:
    """A tool the agent can run: what the model sees (spec) and the function behind it.
    timeout_s and max_chars override the registry's defaults for this one tool (week 3);
    tags mark which lethal-trifecta legs it has (week 7)."""

    spec: ToolSpec
    fn: Callable[..., object]
    timeout_s: float | None = None
    max_chars: int | None = None
    tags: frozenset[str] = frozenset()

    @property
    def name(self) -> str:
        return self.spec.name


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


@dataclass(frozen=True)
class ModelResponse:
    message: Message
    stop_reason: StopReason
    usage: Usage
    raw: dict[str, Any] | None = None
