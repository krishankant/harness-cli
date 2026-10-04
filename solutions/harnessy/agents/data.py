"""The data agent (week 8): answers questions about a SQLite database, read-only."""

from __future__ import annotations

from pathlib import Path

from harnessy.loop import Agent
from harnessy.models.base import Model
from harnessy.tools.data import build_db, data_tools

SYSTEM = (
    "You answer questions about a SQLite database. Look at the tables with list_tables, query with "
    "run_sql, and answer with the number or names asked for. Draw charts with plot_query when asked. "
    "The database is read-only."
)


# --- Week 8 exercise -------------------------------------------------------------------


def make_agent(model: Model, workspace: str | Path) -> Agent:
    """The data agent. Configuration only:

    - db = workspace / "data.db"; if it doesn't exist, build_db(workspace / "data.sql", db)
    - Agent(model, tools=data_tools(db, workspace), system=SYSTEM, max_steps=12)
    """
    workspace = Path(workspace)
    db = workspace / "data.db"
    if not db.exists():
        build_db(workspace / "data.sql", db)
    return Agent(model, tools=data_tools(db, workspace), system=SYSTEM, max_steps=12)
