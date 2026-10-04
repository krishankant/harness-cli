"""Long-term memory (week 4): a small file-backed store the agent reads and writes through
two tools, so a fact from one run is there in the next."""

from __future__ import annotations

import json
import re
from pathlib import Path

from harnessy.tools.schema import tool
from harnessy.types import Tool


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # --- Given ---

    def _load(self) -> dict[str, str]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def remember(self, key: str, text: str) -> str:
        data = self._load()
        data[key] = text
        self._save(data)
        return f"Remembered '{key}'."

    # --- Week 4 exercise ---

    def recall(self, query: str, limit: int = 3) -> str:
        """The memories that best match query, as "- key: text" lines.

        Words are lowercase runs of [a-z0-9] with length >= 3 (so "user_timezone" gives
        "user" and "timezone"). An entry's score is the number of distinct query words that
        also appear in its key + " " + text. Keep entries with score > 0, best first, ties
        by key; return at most `limit`, joined with "\\n". If none match, return
        "No memories match '<query>'."
        """
        words = _words(query)
        scored = sorted((-len(words & _words(f"{k} {v}")), k, v) for k, v in self._load().items())
        hits = [(k, v) for score, k, v in scored if score < 0][:limit]
        if not hits:
            return f"No memories match '{query}'."
        return "\n".join(f"- {k}: {v}" for k, v in hits)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


# --- Given -----------------------------------------------------------------------------


def memory_tools(store: MemoryStore) -> list[Tool]:
    @tool
    def remember(key: str, text: str) -> str:
        """Save a fact to long-term memory so a later run can recall it. Reusing a key replaces the old fact.

        Args:
            key: A short name for the fact, for example "user_timezone".
            text: The fact itself.
        """
        return store.remember(key, text)

    @tool(tags={"private_data"})
    def recall(query: str) -> str:
        """Search long-term memory for facts saved in earlier runs.

        Args:
            query: Words to look for, for example "timezone".
        """
        return store.recall(query)

    return [remember, recall]
