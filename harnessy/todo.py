"""A todo list (week 6): a tool the model uses to plan, plus a hook that shows the current list
to the model on every turn, in the view, never in the history."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from harnessy.hooks import Hook
from harnessy.tools.schema import tool
from harnessy.types import Message, Tool


class TodoList(Hook):
    def __init__(self) -> None:
        self.items: list[list[Any]] = []  # [id, text, done]

    # --- Given ---

    def on_start(self, agent: Any, task: str) -> None:
        self.items = []

    def tool(self) -> Tool:
        @tool
        def todo(action: Literal["add", "complete", "list"], text: str | None = None, id: int | None = None) -> str:
            """Keep a todo list for this task: add items, mark them complete, or list them. The current list is shown to you every turn.

            Args:
                action: "add" a new item, "complete" an item by its number, or "list" all items.
                text: The item text (for "add").
                id: The item number (for "complete").
            """
            return self.apply(action, text, id)

        return todo

    # --- Week 6 exercise ---

    def apply(self, action: str, text: str | None = None, id: int | None = None) -> str:
        """- "add": needs text (else ValueError); items are numbered from 1 -> "Added #<n>: <text>"
        - "complete": needs an existing id (else ValueError naming it) -> "Completed #<id>: <text>"
        - "list": -> self.render()
        - anything else: ValueError."""
        if action == "add":
            if not text:
                raise ValueError("'add' needs text")
            self.items.append([len(self.items) + 1, text, False])
            return f"Added #{len(self.items)}: {text}"
        if action == "complete":
            item = next((i for i in self.items if i[0] == id), None)
            if item is None:
                raise ValueError(f"there is no item #{id}. {self.render()}")
            item[2] = True
            return f"Completed #{id}: {item[1]}"
        if action == "list":
            return self.render()
        raise ValueError(f"unknown action {action!r}: use add, complete or list")

    def render(self) -> str:
        """"Todo list: (empty)", or "Todo list:" then one line per item: "[x] #1 text" (done) or "[ ] #2 text"."""
        if not self.items:
            return "Todo list: (empty)"
        return "Todo list:\n" + "\n".join(f"[{'x' if done else ' '}] #{n} {text}" for n, text, done in self.items)

    def before_model(self, view: list[Message]) -> list[Message] | None:
        """If the list is empty, None. Otherwise a NEW view whose last message has render()
        appended to its text ("<text>\\n\\n<render()>", or just render() if it had no text).
        Use dataclasses.replace; don't change the messages you were given."""
        if not self.items:
            return None
        last = view[-1]
        text = f"{last.text}\n\n{self.render()}" if last.text else self.render()
        return [*view[:-1], replace(last, text=text)]
