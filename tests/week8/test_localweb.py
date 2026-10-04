import pytest

from harnessy.tools.localweb import LocalWeb, web_tools
from harnessy.tools.web import http_get


@pytest.fixture
def web(tmp_path):
    (tmp_path / "railway.md").write_text("# Orwen Valley Railway\n\nThe railway opened in 1887. Its first chief engineer was Ada Voss.\n")
    (tmp_path / "ferry.md").write_text("# Lake Orwen Ferry\n\nThe ferry crosses the lake. The crossing takes 40 minutes.\n")
    (tmp_path / "bridge.md").write_text("# Orwen Bridge\n\nThe bridge opened in 1932. It replaced a railway ferry.\n")
    with LocalWeb(tmp_path) as w:
        yield w


def test_pages_are_loaded_and_served(web):
    assert set(web.pages) == {"railway", "ferry", "bridge"}
    assert web.pages["railway"] == ("Orwen Valley Railway", "The railway opened in 1887. Its first chief engineer was Ada Voss.")
    assert http_get.fn(web.url("railway")).startswith("HTTP 200\n\n# Orwen Valley Railway\n\nThe railway opened")
    assert http_get.fn(web.url("nope")).startswith("HTTP 404")
    assert web.slug_for(web.url("ferry")) == "ferry" and web.slug_for("http://example.com/ferry") is None


def test_search_ranks_title_matches_first(web):
    results = web.search("railway engineer")
    assert [web.slug_for(url) for url, _, _ in results] == ["railway", "bridge"]
    assert results[0][1:] == ("Orwen Valley Railway", "The railway opened in 1887.")
    assert results[1][2] == "It replaced a railway ferry."


def test_no_results_and_limit(web):
    assert web.search("zebra") == []
    assert len(web.search("orwen", limit=2)) == 2


def test_web_search_tool_is_given(web):
    [search] = web_tools(web)
    assert search.tags == frozenset({"untrusted_input"})
    out = search.fn(query="ferry crossing")
    assert out.startswith("1. Lake Orwen Ferry\n   http://127.0.0.1:") and "The ferry crosses the lake." in out
    assert search.fn(query="zebra") == "No results for 'zebra'."
