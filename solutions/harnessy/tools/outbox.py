"""A fake email tool (week 7): it writes to a file instead of sending, so tests and demos can see
whether an injected instruction got through."""

from __future__ import annotations

import json
from pathlib import Path

from harnessy.tools.schema import tool
from harnessy.types import Tool


def outbox_tool(path: str | Path) -> Tool:
    @tool(tags={"external_send"})
    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email.

        Args:
            to: The recipient's address.
            subject: The subject line.
            body: The message text.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as f:
            f.write(json.dumps({"to": to, "subject": subject, "body": body}) + "\n")
        return f"Sent to {to}."

    return send_email
