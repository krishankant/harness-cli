"""Live scripts. `HARNESSY_IMPL=solutions uv run python -m scripts.<name>` runs them
against the reference solutions, to see what a finished week looks like."""

import os
import sys
from pathlib import Path

if os.environ.get("HARNESSY_IMPL") == "solutions":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "solutions"))
