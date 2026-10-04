import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

# Run the suite against the reference solutions with: HARNESSY_IMPL=solutions uv run pytest
if os.environ.get("HARNESSY_IMPL") == "solutions":
    sys.path.insert(0, str(ROOT / "solutions"))


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES / name).read_text())

    return _load
