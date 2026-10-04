import re
from collections import Counter
from pathlib import Path

import pytest

from harnessy.agents import AGENTS, code, data, research
from harnessy.approvals import ApprovalHook
from harnessy.context import ContextManager
from harnessy.evals.runner import run_trial
from harnessy.evals.tasks import EvalTask, load_tasks
from harnessy.hooks import StopCheck
from harnessy.models.scripted import ScriptedModel, text_reply, tool_reply
from harnessy.tools.localweb import LocalWeb
from harnessy.types import ToolCall

ROOT = Path(__file__).resolve().parents[2]
SQL = "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);\nINSERT INTO customers VALUES (1, 'Ana', 'Lisbon'), (2, 'Ben', 'Lisbon'), (3, 'Cai', 'Leeds');\n"
REPO = {
    "calc.py": "def double(x):\n    return x + x + 1\n",
    "test_calc.py": "from calc import double\n\n\ndef test_double():\n    assert double(3) == 6\n",
}
FIX = ToolCall("c1", "edit_file", {"path": "calc.py", "old": "x + x + 1", "new": "x + x"})


@pytest.fixture
def corpus(tmp_path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "railway.md").write_text("# Orwen Valley Railway\n\nIt opened in 1887. Its first chief engineer was Ada Voss.\n")
    return folder


def names(agent):
    return [t.name for t in agent.tools]


def test_the_agents_registry_is_given():
    assert set(AGENTS) == {"research", "code", "data"}


def test_research_agent_passes_the_trifecta_check(corpus, tmp_path):
    with LocalWeb(corpus) as web:
        agent = research.make_agent(ScriptedModel([]), tmp_path, web=web)
        assert names(agent) == ["web_search", "http_get", "remember", "recall", "spawn_subagent"]
        [guard] = [h for h in agent.hooks if isinstance(h, ApprovalHook)]
        assert guard.policy.get("http_get") == "ask" and guard.policy.get("spawn_subagent") == "ask"
        assert guard.approver(ToolCall("c", "http_get", {"url": web.url("railway")}))
        assert not guard.approver(ToolCall("c", "http_get", {"url": "http://evil.example/x"}))
        assert guard.approver(ToolCall("c", "spawn_subagent", {"task": "t"}))
        assert isinstance(agent.context, ContextManager) and agent.max_steps == 15


def test_code_agent_config(tmp_path):
    agent = code.make_agent(ScriptedModel([]), tmp_path)
    assert names(agent) == ["read_file", "write_file", "edit_file", "run_tests"]
    [guard] = [h for h in agent.hooks if isinstance(h, ApprovalHook)]
    assert guard.policy.get("run_tests") == "ask" and guard.approver(ToolCall("c", "run_tests", {}))
    assert any(isinstance(h, StopCheck) for h in agent.hooks) and agent.max_steps == 20


def test_data_agent_builds_its_database(tmp_path):
    (tmp_path / "data.sql").write_text(SQL)
    agent = data.make_agent(ScriptedModel([]), tmp_path)
    assert (tmp_path / "data.db").exists()
    assert names(agent) == ["list_tables", "run_sql", "plot_query"] and agent.max_steps == 12


class FakeResearcher:
    """Searches, reads the first result, and answers citing it."""

    name = "scripted"

    def __init__(self):
        self.calls, self.url = 0, None

    def complete(self, messages, tools, system=None):
        self.calls += 1
        if self.calls == 1:
            return tool_reply(ToolCall("s1", "web_search", {"query": "railway chief engineer"}))
        if self.calls == 2:
            self.url = re.search(r"http://\S+", messages[-1].tool_results[0].content).group(0)
            return tool_reply(ToolCall("g1", "http_get", {"url": self.url}))
        return text_reply(f"Ada Voss was the first chief engineer ({self.url}).")


def test_research_agent_runs_end_to_end(corpus):
    checks = ({"type": "answer_contains", "text": "Ada Voss"}, {"type": "citations", "facts": ["Ada Voss"]})
    task = EvalTask("r", "Who was the railway's first chief engineer?", "easy", checks, agent="research", max_steps=15)
    r = run_trial(task, FakeResearcher(), 1, corpus=corpus)
    assert r.passed, (r.error, r.checks)


def test_code_agent_runs_end_to_end():
    task = EvalTask("c", "Fix the bug.", "easy", ({"type": "command_succeeds", "command": "python -m pytest -q"},), REPO, agent="code", max_steps=5)
    r = run_trial(task, ScriptedModel([tool_reply(FIX), text_reply("Fixed the off-by-one.")]), 1)
    assert r.passed, (r.error, r.checks)


def test_code_agent_is_sent_back_while_the_tests_fail():
    task = EvalTask("c", "Fix the bug.", "easy", ({"type": "command_succeeds", "command": "python -m pytest -q"},), REPO, agent="code", max_steps=5)
    r = run_trial(task, ScriptedModel([text_reply("Done!"), tool_reply(FIX), text_reply("Now it's fixed.")]), 1)
    assert r.passed and r.steps == 3 and r.answer == "Now it's fixed.", (r.error, r.checks)


def test_data_agent_runs_end_to_end():
    model = ScriptedModel([tool_reply(ToolCall("c1", "run_sql", {"sql": "SELECT count(*) FROM customers WHERE city = 'Lisbon'"})), text_reply("2")])
    task = EvalTask("d", "How many customers in Lisbon?", "easy", ({"type": "answer_matches", "pattern": r"\b2\b"},), {"data.sql": SQL}, agent="data", max_steps=5)
    r = run_trial(task, model, 1)
    assert r.passed, (r.error, r.checks)
    assert "2" in model.calls[1].messages[-1].tool_results[0].content


def test_the_capstone_tasks_all_load():
    tasks = load_tasks(ROOT / "evals" / "capstone")
    assert len(tasks) == 15 and Counter(t.agent for t in tasks) == {"research": 5, "code": 5, "data": 5}
    for t in tasks:
        if t.agent == "code":  # a hidden behaviour check the agent can't satisfy by editing the tests
            assert sum(c["type"] == "command_succeeds" for c in t.checks) >= 2, t.id
