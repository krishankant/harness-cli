"""Data tools (week 8): look at a SQLite database, query it read-only, and chart a query.

Read-only is enforced by SQLite itself, not by checking the SQL text (a model can phrase a write
in many ways). Two layers: the file is opened with mode=ro, and an authorizer allows only reading
actions. The second layer matters: mode=ro still lets ATTACH create a new database file and
VACUUM INTO copy the whole database, anywhere on disk."""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path
from typing import Any

from harnessy.tools.files import resolve_inside
from harnessy.tools.schema import tool
from harnessy.types import Tool

# --- Given -----------------------------------------------------------------------------


def build_db(sql_path: str | Path, db_path: str | Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(Path(sql_path).read_text())
        conn.commit()
    finally:
        conn.close()


_READ_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def _only_reads(action: int, *args: object) -> int:
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS else sqlite3.SQLITE_DENY


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """A connection that can't write: the file is opened with mode=ro, and an authorizer denies
    every action except reading (so no ATTACH, VACUUM INTO, PRAGMA or temp tables either)."""
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    conn.set_authorizer(_only_reads)
    return conn


def svg_bar_chart(rows: list[tuple[Any, ...]], width: int = 600, bar_height: int = 24) -> str:
    if not rows or any(len(row) != 2 for row in rows):
        raise ValueError("the query must return rows of exactly two columns: a label and a number")
    values = [float(row[1]) for row in rows]
    top = max(max(values), 0) or 1
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{bar_height * len(rows) + 20}">']
    for i, (row, value) in enumerate(zip(rows, values)):
        y = 10 + i * bar_height
        w = max(0.0, (width - 220) * value / top)
        parts.append(f'<text x="5" y="{y + 16}" font-size="12">{html.escape(str(row[0]))}</text>')
        parts.append(f'<rect x="150" y="{y + 4}" width="{w:.1f}" height="{bar_height - 8}" fill="#4a7ebb"/>')
        parts.append(f'<text x="{155 + w:.1f}" y="{y + 16}" font-size="12">{value:g}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# --- Week 8 exercise -------------------------------------------------------------------


def query_readonly(db_path: str | Path, sql: str, max_rows: int = 50) -> str:
    """Run ONE statement on a connect_readonly connection and format the rows:

        name | city          <- the column names (cursor.description), joined " | "
        Ana | Lisbon         <- one line per row; None shows as NULL
        (2 rows)             <- or "(showing the first 50 rows; add a LIMIT or an aggregate)"

    Fetch max_rows + 1 rows to know whether there were more. Let sqlite3 errors propagate (the
    registry turns them into error results): a write fails with "not authorized", and two
    statements fail because execute() runs only one. Always close the
    connection. A statement with no result columns returns "(the statement returned no rows)".
    """
    conn = connect_readonly(db_path)
    try:
        cursor = conn.execute(sql)
        header = [d[0] for d in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
    finally:
        conn.close()
    if not header:
        return "(the statement returned no rows)"
    lines = [" | ".join(header)]
    lines += [" | ".join("NULL" if v is None else str(v) for v in row) for row in rows[:max_rows]]
    if len(rows) > max_rows:
        lines.append(f"(showing the first {max_rows} rows; add a LIMIT or an aggregate)")
    else:
        lines.append(f"({len(rows)} rows)")
    return "\n".join(lines)


# --- Given -----------------------------------------------------------------------------


def data_tools(db_path: str | Path, root: str | Path) -> list[Tool]:
    @tool
    def list_tables() -> str:
        """List the database's tables with their columns (their CREATE TABLE statements)."""
        return query_readonly(db_path, "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name", max_rows=200)

    @tool
    def run_sql(sql: str) -> str:
        """Run one read-only SQL query (SQLite) and return the rows. Writes are refused.

        Args:
            sql: A single SELECT (or WITH ... SELECT) statement.
        """
        return query_readonly(db_path, sql)

    @tool
    def plot_query(sql: str, out: str) -> str:
        """Draw a bar chart from a query that returns two columns (a label and a number) and save it as an SVG file.

        Args:
            sql: A read-only query returning exactly two columns: label, number.
            out: File name for the chart, for example "chart.svg".
        """
        if not out.lower().endswith(".svg"):
            raise ValueError(f"out must be an .svg file name, for example chart.svg (got {out!r})")
        conn = connect_readonly(db_path)
        try:
            rows = conn.execute(sql).fetchmany(50)
        finally:
            conn.close()
        target = resolve_inside(root, out)
        target.write_text(svg_bar_chart(rows))
        return f"Saved a bar chart with {len(rows)} bars to {out}"

    return [list_tables, run_sql, plot_query]
