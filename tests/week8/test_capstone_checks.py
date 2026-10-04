import textwrap

import pytest

from harnessy.evals.graders import CheckResult, check_citations, grade
from harnessy.evals.tasks import TaskError, load_task, load_tasks
from harnessy.tools.localweb import LocalWeb


@pytest.fixture
def web(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "railway.md").write_text("# Orwen Valley Railway\n\nIt opened in 1887. Its first chief engineer was Ada Voss.\n")
    (corpus / "ferry.md").write_text("# Lake Orwen Ferry\n\nThe crossing takes 40 minutes.\n")
    with LocalWeb(corpus) as w:
        yield w


def test_citations_pass(web):
    answer = f"Ada Voss, in 1887 ({web.url('railway')})."
    assert check_citations(answer, ["Ada Voss", "1887"], web) == CheckResult(True, "1 citation(s), all supported")


def test_markdown_links_and_trailing_punctuation(web):
    answer = f"See [the railway]({web.url('railway')}), and <{web.url('ferry')}>."
    assert check_citations(answer, ["ada voss", "40 minutes"], web) == CheckResult(True, "2 citation(s), all supported")


def test_a_fact_no_cited_page_supports(web):
    assert check_citations(f"It was Ada Voss ({web.url('ferry')}).", ["Ada Voss"], web) == CheckResult(
        False, "no cited page supports: Ada Voss"
    )


def test_pages_that_are_not_on_the_web(web):
    assert not check_citations(f"{web.url('nope')}", ["x"], web).passed
    r = check_citations("http://example.com/railway", ["Ada Voss"], web)
    assert not r.passed and "not a page on the local web" in r.detail


def test_no_citations(web):
    assert check_citations("Ada Voss.", ["Ada Voss"], web) == CheckResult(False, "the answer cites no URLs")


def test_grade_dispatches_the_new_checks(web, tmp_path):
    answer = f"1887 ({web.url('railway')})"
    assert grade({"type": "citations", "facts": ["1887"]}, answer, tmp_path, web=web).passed
    assert grade({"type": "citations", "facts": ["1887"]}, answer, tmp_path) == CheckResult(False, "citations check needs the local web")
    assert grade({"type": "command_succeeds", "command": "python -c 'print(1)'"}, "", tmp_path).passed
    failed = grade({"type": "command_succeeds", "command": "python -c 'import sys; sys.exit(2)'"}, "", tmp_path)
    assert not failed.passed and "exit code 2" in failed.detail


TASK = """
id: d1
prompt: Count them.
difficulty: easy
agent: {agent}
checks:
  - type: answer_matches
    pattern: "3"
"""


def test_tasks_take_an_agent_and_load_from_subfolders(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "d1.yaml").write_text(textwrap.dedent(TASK.format(agent="data")))
    [task] = load_tasks(tmp_path)
    assert task.agent == "data"
    (tmp_path / "bad.yaml").write_text(textwrap.dedent(TASK.format(agent="robot")))
    with pytest.raises(TaskError, match="bad.yaml: unknown agent: robot"):
        load_task(tmp_path / "bad.yaml")


def test_common_url_formats_are_understood(web):
    url = web.url("railway")
    check_citations(f"({url})", ["Ada Voss"], web)  # fails plainly while a stub
    for answer in (f"[{url}]({url})", f"`{url}`", f"**{url}**", f"{url}—see there"):
        assert check_citations(answer, ["Ada Voss"], web).passed, answer
