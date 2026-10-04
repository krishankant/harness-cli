import sqlite3

import pytest

from harnessy.tools.data import build_db, data_tools, query_readonly
from harnessy.tools.registry import ToolRegistry
from harnessy.types import ToolCall

SQL = """CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
INSERT INTO customers VALUES (1, 'Ana', 'Lisbon'), (2, 'Ben', 'Leeds'), (3, 'Cai', NULL);
"""


@pytest.fixture
def db(tmp_path):
    (tmp_path / "data.sql").write_text(SQL)
    build_db(tmp_path / "data.sql", tmp_path / "data.db")
    return tmp_path / "data.db"


def test_rows_and_nulls(db):
    assert query_readonly(db, "SELECT name, city FROM customers ORDER BY id") == "name | city\nAna | Lisbon\nBen | Leeds\nCai | NULL\n(3 rows)"


def test_row_cap_and_no_rows(db):
    assert query_readonly(db, "SELECT name FROM customers ORDER BY id", max_rows=2) == (
        "name\nAna\nBen\n(showing the first 2 rows; add a LIMIT or an aggregate)"
    )
    assert query_readonly(db, "SELECT name FROM customers WHERE 0") == "name\n(0 rows)"


def test_writes_are_refused(db):
    query_readonly(db, "SELECT 1")  # fails plainly while a stub
    with pytest.raises(sqlite3.DatabaseError, match="not authorized|readonly"):
        query_readonly(db, "DELETE FROM customers")
    assert query_readonly(db, "SELECT count(*) AS n FROM customers") == "n\n3\n(1 rows)"


def test_one_statement_at_a_time(db):
    query_readonly(db, "SELECT 1")
    with pytest.raises((sqlite3.ProgrammingError, sqlite3.Warning)):
        query_readonly(db, "SELECT 1; DELETE FROM customers")


def test_data_tools_are_given(db, tmp_path):
    reg = ToolRegistry(data_tools(db, tmp_path))
    assert [s.name for s in reg.specs()] == ["list_tables", "run_sql", "plot_query"]
    assert "CREATE TABLE customers" in reg.call(ToolCall("c1", "list_tables", {})).content
    sql = "SELECT city, count(*) FROM customers WHERE city IS NOT NULL GROUP BY city ORDER BY city"
    chart = reg.call(ToolCall("c2", "plot_query", {"sql": sql, "out": "chart.svg"}))
    assert chart.content == "Saved a bar chart with 2 bars to chart.svg"
    svg = (tmp_path / "chart.svg").read_text()
    assert svg.startswith("<svg") and "Lisbon" in svg and "Leeds" in svg
    bad = reg.call(ToolCall("c3", "plot_query", {"sql": "SELECT name FROM customers", "out": "x.svg"}))
    assert bad.is_error and "two columns" in bad.content


def test_attach_and_vacuum_into_cannot_write_files(db, tmp_path):
    query_readonly(db, "SELECT 1")  # fails plainly while a stub
    for sql in (f"ATTACH DATABASE '{tmp_path}/evil.db' AS e", f"VACUUM INTO '{tmp_path}/copy.db'", "CREATE TEMP TABLE z (a)"):
        with pytest.raises(sqlite3.DatabaseError):
            query_readonly(db, sql)
    assert not (tmp_path / "evil.db").exists() and not (tmp_path / "copy.db").exists()
    assert "1" in query_readonly(db, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 2) SELECT * FROM n")


def test_charts_must_be_svg_files(db, tmp_path):
    reg = ToolRegistry(data_tools(db, tmp_path))
    r = reg.call(ToolCall("c1", "plot_query", {"sql": "SELECT name, id FROM customers", "out": "data.db"}))
    assert r.is_error and ".svg" in r.content
    assert "Ana" in query_readonly(db, "SELECT name FROM customers WHERE id = 1")
