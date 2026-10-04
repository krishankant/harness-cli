"""Context management (week 4): decide what the model sees on each call.

The history (RunResult.messages) is append-only and never edited. ContextManager.prepare
builds a *view* from it: old tool results replaced by stubs, and, once the view is over
budget, the oldest turns dropped or summarized."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import Protocol

from harnessy.models.base import Model
from harnessy.types import Message, ToolResult, Usage

SUMMARY_PROMPT = (
    "You compact an AI agent's working history. Summarize the transcript you are given: facts "
    "learned, files and values found, decisions made, and what is still left to do. Be specific "
    "and brief, at most 200 words. Output only the summary."
)


# --- Given -----------------------------------------------------------------------------


def render_transcript(messages: list[Message]) -> str:
    """Messages as plain text lines, for the summarizer to read."""
    lines: list[str] = []
    for m in messages:
        if m.text:
            lines.append(f"{m.role}: {m.text}")
        for c in m.tool_calls:
            lines.append(f"{m.role} called {c.name}({json.dumps(c.arguments, default=str)})")
        for r in m.tool_results:
            lines.append(f"tool result{' (error)' if r.is_error else ''}: {r.content}")
    return "\n".join(lines)


class Strategy(Protocol):
    reserve_tokens: int

    def view(self, messages: list[Message], cut: int, original: list[Message] | None = None) -> list[Message]: ...

    def reset(self) -> None: ...


class DropOldest:
    """Keep the task and everything from the cut onward; forget the rest."""

    reserve_tokens = 0

    def view(self, messages: list[Message], cut: int, original: list[Message] | None = None) -> list[Message]:
        return [messages[0], *messages[cut:]]

    def reset(self) -> None:
        pass


# --- Week 4 exercise -------------------------------------------------------------------


def estimate_tokens(messages: list[Message]) -> int:
    """A rough token count: ceil(total characters / 4).

    Count per message: if m.raw is set, len(json.dumps(m.raw.content, default=str))
    INSTEAD of text and tool calls (raw is what the Anthropic adapter sends); otherwise
    len(m.text) plus, per tool call, len(name) + len(json.dumps(arguments, default=str)).
    Always add len(content) of each tool result.
    """
    chars = 0
    for m in messages:
        if m.raw is not None:
            chars += len(json.dumps(m.raw.content, default=str))
        else:
            chars += len(m.text) + sum(len(c.name) + len(json.dumps(c.arguments, default=str)) for c in m.tool_calls)
        chars += sum(len(r.content) for r in m.tool_results)
    return math.ceil(chars / 4)


def clear_old_results(messages: list[Message], keep_last: int = 3, min_chars: int = 500) -> list[Message]:
    """Return a new list in which every tool result except the newest `keep_last` (counted
    across all messages) whose content is at least `min_chars` long is replaced by
    ToolResult(same id, "[cleared: read_file result, 5,120 chars]", same is_error).
    The tool name comes from the assistant tool call with the same id ("tool" if none).
    Don't modify the input; messages you don't change go into the output as the same objects.
    """
    names = {c.id: c.name for m in messages for c in m.tool_calls}
    positions = [(i, j) for i, m in enumerate(messages) for j in range(len(m.tool_results))]
    old = set(positions[: len(positions) - keep_last]) if keep_last else set(positions)
    out: list[Message] = []
    for i, m in enumerate(messages):
        if not any((i, j) in old and len(r.content) >= min_chars for j, r in enumerate(m.tool_results)):
            out.append(m)
            continue
        results = tuple(
            ToolResult(r.tool_call_id, f"[cleared: {names.get(r.tool_call_id, 'tool')} result, {len(r.content):,} chars]", r.is_error)
            if (i, j) in old and len(r.content) >= min_chars
            else r
            for j, r in enumerate(m.tool_results)
        )
        out.append(replace(m, tool_results=results))
    return out


def find_cut(messages: list[Message], target_tokens: int, min_cut: int = 1) -> int:
    """Where to cut: the smallest index i >= min_cut (and >= 1) such that messages[i] is an
    assistant turn and estimate_tokens([messages[0], *messages[i:]]) <= target_tokens.

    Cutting only before an assistant turn never separates a tool call from its results,
    and roles still alternate after the task message. If no cut fits, return the index of
    the last assistant turn at or after min_cut; if there is none, return max(min_cut, 1).
    """
    candidates = [i for i in range(max(min_cut, 1), len(messages)) if messages[i].role == "assistant"]
    for i in candidates:
        if estimate_tokens([messages[0], *messages[i:]]) <= target_tokens:
            return i
    return candidates[-1] if candidates else max(min_cut, 1)


class Summarize:
    """Replace the dropped turns with a model-written summary, added to the task message."""

    def __init__(self, model: Model, prompt: str = SUMMARY_PROMPT, reserve_tokens: int = 400):
        self.model = model
        self.prompt = prompt
        self.reserve_tokens = reserve_tokens
        self.usage = Usage()
        self._cut = 1
        self._summary = ""

    def reset(self) -> None:
        self._cut, self._summary = 1, ""

    def view(self, messages: list[Message], cut: int, original: list[Message] | None = None) -> list[Message]:
        """The task (with the summary added) followed by messages[cut:].

        `messages` may have old tool results cleared to stubs; `original` is the same history
        before clearing (default: messages). Summarize from `original`, so the summary keeps
        the facts the stubs hid; build the kept tail from `messages`.

        - cut <= 1: nothing is dropped; return list(messages) with no model call.
        - cut == the cut you summarized last time: reuse the stored summary, no model call.
        - cut > the last cut: summarize only what is newly dropped. Send ONE
          self.model.complete([Message("user", text=...)], [], system=self.prompt) where
          the text is "Summary so far:\n<old summary>\n\n" (only if there is one) +
          "Transcript:\n" + render_transcript(original[last_cut:cut]).
        - cut < the last cut (a new history): summarize messages[1:cut] from scratch.
        Store the reply text, stripped and cut to self.reserve_tokens * 4 characters, and the
        cut. Add the reply's usage to self.usage. If the reply's stop_reason is not
        "end_turn" (refused, cut off, failed), raise RuntimeError naming it and keep nothing:
        a bad summary would silently replace the dropped turns.
        The first message of the view is the task message with its text replaced by
        task.text + "\n\n[Summary of earlier work]\n" + summary (dataclasses.replace).
        """
        if cut <= 1:
            return list(messages)
        if cut != self._cut:
            start, prior = (self._cut, self._summary) if cut > self._cut else (1, "")
            source = original if original is not None else messages
            text = (f"Summary so far:\n{prior}\n\n" if prior else "") + "Transcript:\n" + render_transcript(source[start:cut])
            response = self.model.complete([Message("user", text=text)], [], system=self.prompt)
            self.usage = self.usage + response.usage
            if response.stop_reason != "end_turn":
                raise RuntimeError(f"summary call stopped with '{response.stop_reason}'")
            self._summary = response.message.text.strip()[: self.reserve_tokens * 4]
            self._cut = cut
        task = messages[0]
        return [replace(task, text=f"{task.text}\n\n[Summary of earlier work]\n{self._summary}"), *messages[cut:]]


class ContextManager:
    def __init__(
        self,
        budget_tokens: int = 8000,
        strategy: Strategy | None = None,
        keep_last_results: int = 3,
        target_ratio: float = 0.5,
    ):
        self.budget_tokens = budget_tokens
        self.strategy: Strategy = strategy if strategy is not None else DropOldest()
        self.keep_last_results = keep_last_results
        self.target_ratio = target_ratio
        self.cut: int | None = None
        self._task: Message | None = None

    # --- Given ---

    def _start_if_new(self, history: list[Message]) -> None:
        """A history that starts with a different message is a new run: forget the cut."""
        first = history[0] if history else None
        if first is not self._task:
            self._task, self.cut = first, None
            self.strategy.reset()

    # --- Week 4 exercise ---

    def prepare(self, history: list[Message]) -> list[Message]:
        """The view to send to the model. Never modifies history.

        1. self._start_if_new(history)   (given)
        2. msgs = clear_old_results(history, self.keep_last_results)
        3. view = self.strategy.view(msgs, self.cut, history) if self.cut else msgs
           (history goes along so Summarize can read results that were cleared in msgs)
        4. If estimate_tokens(view) > self.budget_tokens: move the cut forward with
           find_cut(msgs, int(self.budget_tokens * self.target_ratio) - self.strategy.reserve_tokens,
                    min_cut=self.cut or 1),
           store it in self.cut, and rebuild view with self.strategy.view(msgs, self.cut, history).
        The cut only moves when the budget is exceeded, so between compactions the start of
        the view stays the same and the provider's prompt cache keeps hitting.
        """
        self._start_if_new(history)
        msgs = clear_old_results(history, self.keep_last_results)
        view = self.strategy.view(msgs, self.cut, history) if self.cut else msgs
        if estimate_tokens(view) > self.budget_tokens:
            target = int(self.budget_tokens * self.target_ratio) - self.strategy.reserve_tokens
            self.cut = find_cut(msgs, target, min_cut=self.cut or 1)
            view = self.strategy.view(msgs, self.cut, history)
        return view
